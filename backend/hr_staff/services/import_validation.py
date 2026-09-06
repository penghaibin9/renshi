"""School-scoped, effective-dated reference validation for verified staff import.

Preview bulk-loads only referenced objects. Commit rebuilds the same snapshot
under locks; preview is never a permission, capacity reservation or authority.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from hr_staff.constants import RelationshipType, StaffCategoryCode
from hr_staff.models import HrPerson, HrPersonIdentityDocument, HrStaffAssignment, HrStaffMaster
from hr_staff.services.crypto import document_fingerprint, normalize_document_number
from hr_structure.models import (
    HrOrganization, HrOrganizationVersion, HrPosition, HrPositionReservation, HrPositionVersion,
)


class ImportRowError(ValueError):
    code = "IMPORT_ROW_INVALID"

    def __init__(self, field, message):
        self.field = field
        self.message = message
        super().__init__(message)


def parse_date(value):
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value or "").strip(), pattern).date()
        except ValueError:
            continue
    return None


def basic_errors(row, *, today=None):
    today = today or timezone.localdate()
    errors = {}
    for key, limit in (("legal_name", 200), ("staff_no", 64), ("organization_code", 64), ("position_code", 64)):
        value = str(row.get(key) or "").strip()
        if not value or len(value) > limit:
            errors[key] = f"必填且不能超过 {limit} 个字符"
        elif key != "legal_name" and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            errors[key] = "编码只允许字母、数字、下划线或连字符"
    if row.get("legacy_department_id"):
        errors["legacy_department_id"] = "旧部门编号不能作为正式归属，请填写本校 HR02 组织和岗位编码"
    if row.get("gender_code") and row["gender_code"] not in ("M", "F", "O", "U"):
        errors["gender_code"] = "只允许 M/F/O/U"
    if (row.get("staff_category_code") or "TEACHER") not in StaffCategoryCode.values:
        errors["staff_category_code"] = "人员类别代码无效"
    relationship = row.get("relationship_type") or "REGULAR_EMPLOYMENT"
    if relationship not in RelationshipType.values or relationship == "EXTERNAL_PART_TIME":
        errors["relationship_type"] = "聘用关系代码无效；外聘人员请走 HR08，不导入内部主档"
    effective = parse_date(row.get("effective_from"))
    if effective is None or effective > today:
        errors["effective_from"] = "填写不晚于今天的任职生效日；未来入职请通过 HR05 办理"
    birth = parse_date(row.get("birth_date"))
    if row.get("birth_date") and (birth is None or birth > today):
        errors["birth_date"] = "出生日期无效，请填写 YYYY-MM-DD"
    if birth is not None and effective is not None and birth > effective:
        errors["effective_from"] = "任职生效日不能早于出生日期"
    document = row.get("document_number") or ""
    if document and (not re.fullmatch(r"[A-Za-z0-9 -]{6,64}", document)
                     or len(normalize_document_number(document)) < 6):
        errors["document_number"] = "证件字段格式无效，请检查原文件，不在错误清单回显证件号"
    try:
        fte = Decimal(row.get("fte") or "1.00")
        if not fte.is_finite() or not Decimal("0.01") <= fte <= Decimal("1.50") or fte != fte.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        errors["fte"] = "工作量必须为 0.01 至 1.50，最多两位小数"
    return errors


def _at(versions, day, *, status_field, statuses):
    matches = [v for v in versions if getattr(v, status_field) in statuses
               and v.validity_from <= day and (v.validity_to is None or day < v.validity_to)]
    if len(matches) != 1:
        return None
    return matches[0]


def peak_usage(intervals, start):
    """Peak simultaneous occupants/FTE for an open-ended proposed assignment."""
    events = defaultdict(lambda: [0, Decimal("0")])
    for beginning, end, fte in intervals:
        if end is not None and end <= start:
            continue
        event = events[max(start, beginning)]
        event[0] += 1
        event[1] += Decimal(str(fte))
        if end is not None:
            events[end][0] -= 1
            events[end][1] -= Decimal(str(fte))
    count = max_count = 0
    fte = max_fte = Decimal("0")
    for day in sorted(events):
        count += events[day][0]
        fte += events[day][1]
        max_count, max_fte = max(max_count, count), max(max_fte, fte)
    return max_count, max_fte


class StructureReferences:
    def __init__(self, tenant_id, rows, *, lock=False):
        self.tenant_id = tenant_id
        org_codes = {row.get("organization_code") for row in rows if row.get("organization_code")}
        pos_codes = {row.get("position_code") for row in rows if row.get("position_code")}
        positions = HrPosition.objects.filter(tenant_id=tenant_id, position_code__in=pos_codes)
        organizations = HrOrganization.objects.filter(tenant_id=tenant_id, stable_code__in=org_codes)
        if lock:
            positions, organizations = positions.select_for_update(), organizations.select_for_update()
        # Stable position locks are also acquired by HR02 reservation writers.
        self.positions = {item.position_code.casefold(): item for item in positions.order_by("pk")}
        self.organizations = {item.stable_code.casefold(): item for item in organizations.order_by("pk")}
        self.org_versions, self.pos_versions = defaultdict(list), defaultdict(list)
        org_ids = [item.pk for item in self.organizations.values()]
        pos_ids = [item.pk for item in self.positions.values()]
        for item in HrOrganizationVersion.objects.filter(tenant_id=tenant_id, organization_id_id__in=org_ids,
                                                         status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED")):
            self.org_versions[item.organization_id_id].append(item)
        for item in HrPositionVersion.objects.filter(tenant_id=tenant_id, position_id_id__in=pos_ids).select_related("post_catalog_version_id"):
            self.pos_versions[item.position_id_id].append(item)
        self.intervals = defaultdict(list)
        assignments = HrStaffAssignment.objects.filter(tenant_id=tenant_id, position_id_id__in=pos_ids,
                                                        status__in=("ACTIVE", "ENDED"))
        for pos, beginning, end, fte in assignments.values_list("position_id_id", "effective_from", "effective_to", "fte"):
            self.intervals[pos].append((beginning, end, fte))
        self.holds = defaultdict(lambda: [0, Decimal("0")])
        for pos, count, fte in HrPositionReservation.objects.filter(
                tenant_id=tenant_id, position_id_id__in=pos_ids, status="HELD",
                expires_at__gt=timezone.now()).values_list("position_id_id", "reserved_count", "reserved_fte"):
            self.holds[pos][0] += count
            self.holds[pos][1] += fte

    def resolve(self, row, *, plan=False):
        day = parse_date(row.get("effective_from"))
        fte = Decimal(row.get("fte") or "1.00")
        org = self.organizations.get(str(row.get("organization_code") or "").casefold())
        pos = self.positions.get(str(row.get("position_code") or "").casefold())
        if org is None:
            raise ImportRowError("organization_code", "本校不存在该组织编码，请从本校组织台账核对")
        if pos is None:
            raise ImportRowError("position_code", "本校不存在该岗位编码，请从本校岗位台账核对")
        version = _at(self.org_versions[org.pk], day, status_field="status", statuses=("APPROVED", "EFFECTIVE", "SUPERSEDED"))
        pv = _at(self.pos_versions[pos.pk], day, status_field="lifecycle_status", statuses=("ACTIVE",))
        if version is None or version.validity_to is not None:
            raise ImportRowError("organization_code", "组织在生效日无唯一正式版本或已有结束日期，请先核对历史归属")
        # Positions predating versioning use the established stable projection.
        if pv is None and not self.pos_versions[pos.pk] and pos.validity_from <= day and pos.validity_to is None:
            pv = pos
        if pv is None or pv.lifecycle_status != "ACTIVE" or pos.lifecycle_status != "ACTIVE":
            raise ImportRowError("position_code", "岗位在生效日未正式生效或已冻结、关闭")
        if pv.organization_id_id != org.pk or pos.organization_id_id != org.pk:
            raise ImportRowError("position_code", "岗位与所填组织不一致；历史调岗应分段办理")
        if pv.validity_to is not None or pos.validity_to is not None or any(
                v.validity_from > day for v in self.pos_versions[pos.pk]):
            raise ImportRowError("position_code", "岗位已有后续变更，请核对任职区间后通过正式任职流程办理")
        catalog = pv.post_catalog_version_id
        if catalog.tenant_id != self.tenant_id or catalog.status != "ACTIVE" or catalog.validity_from > day or (
                catalog.validity_to is not None and day >= catalog.validity_to):
            raise ImportRowError("position_code", "岗位目录版本无效，请先完成 HR02 配置")
        count, used = peak_usage(self.intervals[pos.pk], day)
        reserved, reserved_fte = self.holds[pos.pk]
        maximum = pv.max_incumbents if pv.allow_multiple_incumbents else min(pv.max_incumbents, 1)
        if maximum <= 0 or count + reserved + 1 > maximum or used + reserved_fte + fte > pv.planned_fte:
            raise ImportRowError("position_code", "岗位人数或工作量容量不足（含有效预占及已排定任职），请核对岗位台账")
        snapshot = {"organization": org.pk, "organizationVersion": version.pk, "position": pos.pk,
                    "positionVersion": pv.pk if pv is not pos else None, "catalogVersion": catalog.pk}
        if row.get("_structure_snapshot") and row["_structure_snapshot"] != snapshot:
            raise ImportRowError("position_code", "预检后组织或岗位版本已变化，请重新上传预检")
        if plan:
            self.intervals[pos.pk].append((day, None, fte))
        return org, pos, catalog, snapshot


class StaffImportValidator:
    def __init__(self, tenant_id, rows, *, today=None):
        self.tenant_id = tenant_id
        self.today = today or timezone.localdate()
        self.refs = StructureReferences(tenant_id, rows)
        self.staff_seen, self.documents_seen, self.snapshots = set(), set(), {}
        self.people_seen = set()
        names = {row.get("legal_name") for row in rows if row.get("legal_name")}
        births = {parse_date(row.get("birth_date")) for row in rows if parse_date(row.get("birth_date"))}
        self.existing_people = {(name.casefold(), birth) for name, birth in HrPerson.objects.filter(
            tenant_id=tenant_id, legal_name__in=names, birth_date__in=births).values_list("legal_name", "birth_date")}
        numbers = {row.get("staff_no") for row in rows if row.get("staff_no")}
        self.existing_staff = {value.casefold() for value in HrStaffMaster.objects.filter(
            tenant_id=tenant_id, staff_no__in=numbers).values_list("staff_no", flat=True)}
        fingerprints = [document_fingerprint(tenant_id, normalize_document_number(row.get("document_number")))
                        for row in rows if row.get("document_number")]
        self.existing_documents = set(HrPersonIdentityDocument.objects.filter(
            tenant_id=tenant_id, document_number_fingerprint__in=fingerprints).values_list("document_number_fingerprint", flat=True))

    def __call__(self, row):
        errors = basic_errors(row, today=self.today)
        staff = str(row.get("staff_no") or "").casefold()
        fingerprint = document_fingerprint(self.tenant_id, normalize_document_number(row.get("document_number")))
        if staff and staff in self.staff_seen | self.existing_staff:
            errors["staff_no"] = "工号在本校已存在或在文件中重复，禁止覆盖原人员"
        if fingerprint and fingerprint in self.documents_seen | self.existing_documents:
            errors["document_number"] = "身份信息已存在或在文件中重复，请人工核对，系统不自动合并"
        person_key = (str(row.get("legal_name") or "").casefold(), parse_date(row.get("birth_date")))
        if person_key[1] and person_key in self.people_seen | self.existing_people:
            errors["legal_name"] = "姓名和出生日期疑似重复，请先人工核对，系统不自动合并"
        if person_key[1]:
            self.people_seen.add(person_key)
        # Repeated IDs remain ambiguous even if an earlier row has other errors.
        self.staff_seen.add(staff)
        if fingerprint:
            self.documents_seen.add(fingerprint)
        if not errors:
            try:
                *_, snapshot = self.refs.resolve(row, plan=True)
                self.snapshots[staff] = snapshot
            except ImportRowError as exc:
                errors[exc.field] = exc.message
        return errors

    def enrich(self, row):
        return {"_structure_snapshot": self.snapshots[str(row["staff_no"]).casefold()]}
