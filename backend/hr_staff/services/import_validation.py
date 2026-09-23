"""Canonical HR03 staff-import validation shared by preview and authority commit.

The import pipeline must never rely on model defaults for business facts.  Every
path that can write authority data (fresh upload, historical staged job, retry,
or stale-owner recovery) is revalidated here immediately before the first
Person/Staff/Employment/Assignment write.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Iterable

from hr_staff.constants import RelationshipType, StaffCategoryCode


VALUE_ALIASES = {
    "gender_code": {"男": "M", "女": "F", "其他": "O", "未知": "U"},
    "staff_category_code": {
        "教师": "TEACHER",
        "行政": "ADMIN",
        "工程技术": "ENGINEERING_TECHNICAL",
        "实验": "EXPERIMENTAL",
        "图书档案": "LIBRARY_ARCHIVES",
        "工勤": "LOGISTICS",
        "其他": "OTHER",
    },
    "relationship_type": {
        "在编": "REGULAR_EMPLOYMENT",
        "合同聘用": "CONTRACT",
        "劳务派遣": "LABOR_DISPATCH",
        "校外兼职": "EXTERNAL_PART_TIME",
        "借调": "SECONDMENT",
        "退休返聘": "RETIRED_REHIRE",
        "返聘": "REHIRE",
        "其他": "OTHER",
    },
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y")


class ImportRowValidationError(ValueError):
    """Safe, field-scoped validation failure for a staged HR03 row."""

    code = "IMPORT_ROW_VALIDATION_FAILED"

    def __init__(self, errors: dict[str, str]):
        self.errors = dict(errors)
        message = "；".join(f"{field}：{text}" for field, text in self.errors.items())
        super().__init__(message or "导入行校验失败")


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_staff_import_row(row: dict) -> dict:
    """Return a normalized copy without inventing any missing business fact."""
    normalized = dict(row or {})
    for key, aliases in VALUE_ALIASES.items():
        value = _text(normalized.get(key))
        normalized[key] = aliases.get(value, value)
    for key in (
        "staff_no",
        "legal_name",
        "gender_code",
        "birth_date",
        "document_number",
        "staff_category_code",
        "relationship_type",
        "effective_from",
        "legacy_department_id",
        "department_name",
    ):
        if key in normalized:
            normalized[key] = _text(normalized.get(key))
    return normalized


def is_supported_import_date(value) -> bool:
    if isinstance(value, datetime):
        return True
    if isinstance(value, date):
        return True
    text = _text(value)
    if not text:
        return False
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def parse_import_date(value, *, field: str, required: bool) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        if required:
            raise ImportRowValidationError({field: "必填，不能由系统自动补当天日期"})
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ImportRowValidationError(
        {field: "日期格式应为 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY，且必须是真实日期"}
    )


def validate_staff_import_fields(row: dict) -> dict[str, str]:
    """Pure field validation used by both preview and pre-commit validation."""
    row = normalize_staff_import_row(row)
    errors: dict[str, str] = {}

    legal_name = _text(row.get("legal_name"))
    if not legal_name:
        errors["legal_name"] = "必填"
    elif len(legal_name) > 200:
        errors["legal_name"] = "不能超过 200 个字符"

    staff_no = _text(row.get("staff_no"))
    if len(staff_no) > 64:
        errors["staff_no"] = "不能超过 64 个字符"

    gender = _text(row.get("gender_code"))
    if gender and gender not in {"M", "F", "O", "U"}:
        errors["gender_code"] = "只允许 M/F/O/U"

    category = _text(row.get("staff_category_code"))
    if not category:
        errors["staff_category_code"] = "请填写真实人员类别（教师、行政等），不能留空"
    elif category not in {code for code, _ in StaffCategoryCode.choices}:
        errors["staff_category_code"] = "人员类别不在允许枚举中"

    relationship = _text(row.get("relationship_type"))
    if not relationship:
        errors["relationship_type"] = "请填写真实聘用关系，不能留空"
    elif relationship not in {code for code, _ in RelationshipType.choices}:
        errors["relationship_type"] = "聘用关系不在允许枚举中"

    effective_from = row.get("effective_from")
    if not _text(effective_from):
        errors["effective_from"] = "请填写真实入职日期，不会自动编造为今天"
    elif not is_supported_import_date(effective_from):
        errors["effective_from"] = "日期格式应为 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY，且必须是真实日期"

    birth_date = row.get("birth_date")
    if _text(birth_date) and not is_supported_import_date(birth_date):
        errors["birth_date"] = "日期格式应为 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY，且必须是真实日期"

    legacy_department_id = _text(row.get("legacy_department_id"))
    if legacy_department_id:
        try:
            if int(legacy_department_id) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors["legacy_department_id"] = "必须是正整数"
    return errors


def build_staff_import_row_validator(tenant_id: int, rows: list[dict]):
    """Batch preview validator; resolves only an active department in this school."""
    from base.models import Department
    from hr_staff.models import HrStaffMaster

    departments = list(
        Department.objects.entire()
        .filter(company_id=tenant_id, is_active=True)
        .values_list("pk", "department")
        .distinct()
    )
    by_id = {str(pk): _text(name) for pk, name in departments}
    by_name: dict[str, list[str]] = {}
    for pk, name in departments:
        by_name.setdefault(_text(name), []).append(str(pk))

    for index, row in enumerate(rows, start=2):
        normalized = normalize_staff_import_row(row)
        row.update(normalized)
        source_row = row.get("_source_row_no", index)
        number = _text(row.get("legacy_department_id"))
        name = _text(row.get("department_name"))
        department_error = ""
        if number and number in by_id and (not name or name == by_id[number]):
            row["legacy_department_id"] = number
            row["department_name"] = by_id[number]
        elif not number and len(by_name.get(name, [])) == 1:
            row["legacy_department_id"] = by_name[name][0]
            row["department_name"] = name
        else:
            department_error = "请选择本校已建立且仍有效、名称唯一的部门；名称与编号同时填写时必须一致"
        if department_error:
            row["_department_error"] = department_error
        else:
            row.pop("_department_error", None)

    numbers = [_text(r.get("staff_no")) for r in rows]
    duplicates = Counter(n.casefold() for n in numbers if n)
    existing = {
        n.casefold()
        for n in HrStaffMaster.objects.filter(tenant_id=tenant_id, staff_no__in=numbers).values_list(
            "staff_no", flat=True
        )
    }
    # Typical first-use files contain many people in the same department with the
    # same joining date. Cache the read-only HR02 mapping/effective-date lookup so
    # preview stays O(unique department/date) instead of O(rows) authority queries.
    hr02_resolution_cache: dict[tuple[int, date], tuple[object | None, str]] = {}

    def validate(row: dict) -> dict[str, str]:
        errors = validate_staff_import_fields(row)
        if row.get("_department_error"):
            errors["department_name"] = _text(row["_department_error"])
        elif "effective_from" not in errors:
            try:
                as_of = parse_import_date(
                    row.get("effective_from"), field="effective_from", required=True
                )
            except ImportRowValidationError as exc:
                errors.update(exc.errors)
            else:
                cache_key = (int(row["legacy_department_id"]), as_of)
                if cache_key not in hr02_resolution_cache:
                    hr02_resolution_cache[cache_key] = resolve_hr02_organization_for_department(
                        tenant_id, cache_key[0], as_of=as_of
                    )
                _, mapping_error = hr02_resolution_cache[cache_key]
                if mapping_error:
                    errors["department_name"] = mapping_error
        number = _text(row.get("staff_no")).casefold()
        if number and duplicates[number] > 1:
            errors["staff_no"] = "本文件中工号重复，请只保留一条"
        elif number and number in existing:
            errors["staff_no"] = "本校已有该工号，请在名册中更正，不要重复新增"
        return errors

    return validate


def _resolve_current_department(tenant_id: int, row: dict, *, for_update: bool):
    from base.models import Department

    qs = Department.objects.entire().filter(company_id=tenant_id, is_active=True)
    if for_update:
        # Keep the lock query simple for MySQL; one department/company M2M row
        # is unique, so DISTINCT is unnecessary and can weaken/forbid FOR UPDATE.
        qs = qs.select_for_update()

    number = _text(row.get("legacy_department_id"))
    name = _text(row.get("department_name"))
    if number:
        try:
            department_id = int(number)
            if department_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return None, "部门编号必须是正整数"
        department = qs.filter(pk=department_id).first()
        if department is None:
            return None, "部门不存在、已停用或不属于本校"
        if name and _text(department.department) != name:
            return None, "部门名称与当前本校部门编号不一致"
        return department, ""

    if not name:
        return None, "请选择本校已建立且仍有效的部门"
    matches = list(qs.filter(department=name)[:2])
    if len(matches) != 1:
        return None, "部门名称在本校不存在、已停用或不唯一"
    return matches[0], ""


def resolve_hr02_organization_for_department(
    tenant_id: int, department_id: int, *, as_of: date, for_update: bool = False
):
    """Resolve a legacy Department to HR02 authority without guessing by name.

    LEGACY/DUAL modes may still have an unmapped department during migration.  Once
    HR02 is authoritative, however, a formal HR03 assignment must carry the mapped
    authority organization or the write fails closed.
    """
    from hr_structure.models import HrLegacyObjectLink, HrOrganization
    from hr_structure.selectors.effective import org_version_as_of
    from hr_structure.services.cutover import Hr02CutoverService

    link_qs = HrLegacyObjectLink.objects.filter(
        tenant_id=tenant_id,
        domain_entity_type="organization",
        legacy_app="base",
        legacy_model="department",
        legacy_pk=str(department_id),
        link_status="MAPPED",
    ).order_by("id")
    if for_update:
        link_qs = link_qs.select_for_update()
    link = link_qs.first()
    mode = Hr02CutoverService().get_mode(tenant_id)
    if link is None:
        if mode == "HR02_AUTHORITY":
            return None, "本校已启用 HR02 权威组织，该部门尚未完成权威映射，禁止只写旧部门"
        return None, ""

    try:
        organization_pk = int(link.domain_entity_id)
    except (TypeError, ValueError):
        return None, "部门的 HR02 权威映射损坏，请先修复组织映射"
    organization_qs = HrOrganization.objects.filter(
        tenant_id=tenant_id, pk=organization_pk
    )
    if for_update:
        organization_qs = organization_qs.select_for_update()
    organization = organization_qs.first()
    if organization is None:
        return None, "部门的 HR02 权威组织不存在或不属于本校"
    version = org_version_as_of(tenant_id, organization.pk, as_of)
    if version is None:
        return None, f"该部门对应的 HR02 组织在 {as_of} 无有效版本"
    if organization.identity_status == "CLOSED":
        closed_at = organization.closed_at
        if closed_at is None or as_of >= closed_at.date():
            return None, f"该部门对应的 HR02 组织在 {as_of} 已关闭"
    return organization, ""


def validate_staff_import_row_for_commit(tenant_id: int, row: dict) -> dict:
    """Revalidate a staged row under row transaction immediately before writes.

    This deliberately does not trust preview flags or historical staging data.
    The active department is row-locked; enums and effective date are mandatory;
    current StaffMaster state is checked again to close preview-to-commit races.
    """
    from hr_staff.models import HrStaffMaster

    normalized = normalize_staff_import_row(row)
    errors = validate_staff_import_fields(normalized)
    department, department_error = _resolve_current_department(
        tenant_id, normalized, for_update=True
    )
    if department_error:
        errors["department_name"] = department_error

    staff_no = _text(normalized.get("staff_no"))
    if staff_no and HrStaffMaster.objects.filter(tenant_id=tenant_id, staff_no=staff_no).exists():
        errors["staff_no"] = "本校已有该工号，请在名册中更正，不要重复新增"

    hr02_org = None
    if department is not None and "effective_from" not in errors:
        try:
            as_of = parse_import_date(
                normalized.get("effective_from"), field="effective_from", required=True
            )
        except ImportRowValidationError as exc:
            errors.update(exc.errors)
        else:
            hr02_org, mapping_error = resolve_hr02_organization_for_department(
                tenant_id, department.pk, as_of=as_of, for_update=True
            )
            if mapping_error:
                errors["department_name"] = mapping_error

    if errors:
        raise ImportRowValidationError(errors)

    normalized["legacy_department_id"] = str(department.pk)
    normalized["department_name"] = _text(department.department)
    normalized["_hr02_organization_id"] = hr02_org.pk if hr02_org is not None else None
    return normalized
