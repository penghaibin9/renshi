"""Empty-state setup boundaries for HR14 policies, supply and quota."""

from __future__ import annotations

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from hr_appointment.api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from hr_appointment.application_api import _resolve_applicant_person_id
from hr_appointment.models import (
    AppointmentBatch,
    AppointmentPolicyVersion,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)
from hr_appointment.permissions import APPLICATION_PERMISSION, MANAGE_PERMISSION
from hr_appointment.population_models import AppointmentPopulationMemberSnapshot
from hr_staff.models import HrPerson
from hr_structure.models import HrPosition
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.position import PositionSelector


def _canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_policy(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
        body = _payload(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    code = str(body.get("policyCode") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    effective_from = parse_date(str(body.get("effectiveFrom") or ""))
    effective_to = parse_date(str(body.get("effectiveTo") or "")) if body.get("effectiveTo") else None
    if not code or not name or not effective_from or (effective_to and effective_to <= effective_from):
        return _error("APPOINTMENT_POLICY_INPUT_INVALID", "请填写有效的制度代码、名称和生效日期", status=400)
    try:
        with transaction.atomic():
            versions = AppointmentPolicyVersion.objects.select_for_update().filter(
                tenant_id=tenant_id,
                policy_code=code,
            )
            latest = versions.order_by("-version_no").first()
            overlap = versions.filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from)
            )
            if effective_to:
                overlap = overlap.filter(effective_from__lte=effective_to)
            if overlap.exists():
                return _error(
                    "APPOINTMENT_POLICY_EFFECTIVE_OVERLAP",
                    "同一制度代码的生效区间不能重叠，请先调整旧版本截止日期",
                    status=409,
                )
            policy = AppointmentPolicyVersion(
                tenant_id=tenant_id,
                policy_code=code,
                name=name,
                position_category=str(body.get("positionCategory") or "").strip(),
                level_code=str(body.get("levelCode") or "").strip(),
                effective_from=effective_from,
                effective_to=effective_to,
                version_no=(latest.version_no if latest else 0) + 1,
                status="PUBLISHED",
                created_by=getattr(request.user, "id", None),
                updated_by=getattr(request.user, "id", None),
            )
            policy.full_clean()
            policy.save()
    except ValidationError:
        return _error(
            "APPOINTMENT_POLICY_INPUT_INVALID",
            "聘任制度数据不符合约束，请检查代码、名称和生效区间",
            status=400,
        )
    except IntegrityError:
        return _error(
            "APPOINTMENT_POLICY_VERSION_CONFLICT",
            "制度版本发生并发冲突，请刷新后重试",
            status=409,
        )
    return JsonResponse({"data": {"id": str(policy.id), "versionNo": policy.version_no, "status": policy.status}}, status=201)


def setup_options(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    policies = AppointmentPolicyVersion.objects.filter(
        tenant_id=tenant_id, status="PUBLISHED"
    ).order_by("policy_code", "-version_no")
    position_page = PositionSelector(Hr02Scope("SCHOOL", tenant_id)).list_positions(
        lifecycle_status=HrPosition.LifecycleStatus.ACTIVE, page_size=500
    )
    positions = [item for item in position_page["items"] if item["availableCount"] > 0]
    open_batches = list(AppointmentBatch.objects.filter(
        tenant_id=tenant_id, status=AppointmentBatch.Status.APPLICATION_OPEN
    ).order_by("batch_no"))
    targets = []
    for batch in open_batches:
        for supply in AppointmentPositionSupplySnapshot.objects.filter(tenant_id=tenant_id, batch=batch):
            targets.append({
                "batchNo": batch.batch_no, "policyVersionId": str(batch.policy_version_id),
                "positionInstanceId": supply.position_instance_id, "levelCode": supply.level_code,
                "label": f"{batch.name} · 岗位 {supply.position_instance_id} · {supply.level_code or '未分级'}",
            })
    applicant_ids = set()
    if getattr(request.user, "is_superuser", False) or request.user.has_perm(MANAGE_PERMISSION):
        applicant_ids.update(AppointmentPopulationMemberSnapshot.objects.filter(
            tenant_id=tenant_id, snapshot__batch__in=open_batches
        ).values_list("person_id", flat=True))
    else:
        try:
            applicant_ids.add(_resolve_applicant_person_id(request, tenant_id))
        except HrAppointmentAccessError:
            pass
    people = HrPerson.objects.filter(tenant_id=tenant_id, id__in=applicant_ids).order_by("legal_name")
    return JsonResponse({"data": {
        "policies": [{"value": str(item.id), "label": f"{item.name} · {item.policy_code} v{item.version_no}"} for item in policies],
        "positions": [{"value": item["id"], "label": f"{item['positionCode']} · {item['postCatalog'] or '岗位'} · 可用 {item['availableCount']}", **item} for item in positions],
        "openTargets": targets,
        "applicants": [{"value": str(item.id), "label": item.legal_name} for item in people],
    }})


def configure_supply_quota(request, batch_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
        body = _payload(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        position_id = int(body.get("positionInstanceId"))
        authorized = int(body.get("authorized"))
    except (TypeError, ValueError):
        return _error("APPOINTMENT_QUOTA_INPUT_INVALID", "请选择岗位并填写正整数额度", status=400)
    try:
        with transaction.atomic():
            batch = AppointmentBatch.objects.select_for_update().filter(
                id=batch_id,
                tenant_id=tenant_id,
                status__in=[
                    AppointmentBatch.Status.DRAFT,
                    AppointmentBatch.Status.CONFIGURING,
                ],
            ).first()
            if batch is None:
                return _error(
                    "APPOINTMENT_BATCH_NOT_CONFIGURABLE",
                    "当前学校没有可配置的草稿批次",
                    status=409,
                )
            position = (
                HrPosition.objects.select_for_update()
                .select_related("post_catalog_version_id", "post_grade_id")
                .filter(id=position_id, tenant_id=tenant_id)
                .first()
            )
            if position is None:
                return _error(
                    "APPOINTMENT_POSITION_NOT_ACTIVE",
                    "所选岗位不属于当前学校或当前不可用",
                    status=404,
                )
            dto = PositionSelector(Hr02Scope("SCHOOL", tenant_id)).get_position(
                position_id
            )
            if dto is None or dto["lifecycleStatus"] != HrPosition.LifecycleStatus.ACTIVE:
                return _error(
                    "APPOINTMENT_POSITION_NOT_ACTIVE",
                    "所选岗位不属于当前学校或当前不可用",
                    status=404,
                )
            if authorized <= 0 or authorized > dto["availableCount"]:
                return _error(
                    "APPOINTMENT_QUOTA_EXCEEDS_SUPPLY",
                    "批次额度必须大于 0 且不能超过 HR02 当前可用量",
                    status=409,
                )
            category = position.post_catalog_version_id.category
            level = position.post_grade_id.code if position.post_grade_id_id else ""
            source = {
                "positionId": position.id,
                "version": position.version,
                "occupied": dto["occupiedCount"],
                "reserved": dto["reservedCount"],
                "available": dto["availableCount"],
                "capturedAt": timezone.now().isoformat(),
            }
            supply, _ = AppointmentPositionSupplySnapshot.objects.update_or_create(
                tenant_id=tenant_id, batch=batch, position_instance_id=position.id,
                defaults={
                    "organization_id": position.organization_id_id, "category_code": category,
                    "level_code": level, "authorized_fte": position.planned_fte,
                    "occupied_fte": dto["occupiedCount"], "reserved_fte": dto["reservedCount"],
                    "available_fte": dto["availableCount"], "snapshot_at": timezone.now(),
                    "source_version": str(position.version), "source_hash": _canonical_hash(source),
                },
            )
            pool, _ = AppointmentQuotaPool.objects.update_or_create(
                tenant_id=tenant_id, batch=batch, scope_type="SCHOOL", scope_org_id=None,
                category_code=category, level_group_code="", exact_level_code=level,
                defaults={"authorized": authorized, "occupied": 0, "reserved": 0, "exception_quota": 0},
            )
            batch.target_categories_json = sorted(set((batch.target_categories_json or []) + [category]))
            batch.target_levels_json = sorted(set((batch.target_levels_json or []) + ([level] if level else [])))
            batch.status = AppointmentBatch.Status.CONFIGURING
            batch.save(update_fields=["target_categories_json", "target_levels_json", "status", "updated_at"])
    except IntegrityError:
        return _error(
            "APPOINTMENT_QUOTA_CONFLICT",
            "批次岗位或额度发生并发冲突，请刷新后重试",
            status=409,
        )
    return JsonResponse({"data": {"supplyId": str(supply.id), "quotaPoolId": str(pool.id), "available": pool.available}}, status=201)
