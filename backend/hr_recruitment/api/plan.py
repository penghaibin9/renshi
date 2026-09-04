"""
hr_recruitment/api/plan.py

HR04-01 年度用人计划 API（总册 8.5）。

  GET    /api/hr/v1/recruitment/plans
  POST   /api/hr/v1/recruitment/plans
  GET    /api/hr/v1/recruitment/plans/{id}
  POST   /api/hr/v1/recruitment/plans/{id}/submit
  POST   /api/hr/v1/recruitment/plans/{id}/approve

  POST   /api/hr/v1/recruitment/plan-requests
  PATCH  /api/hr/v1/recruitment/plan-requests/{id}
  POST   /api/hr/v1/recruitment/plan-requests/{id}/submit
  POST   /api/hr/v1/recruitment/plan-requests/{id}/return
  POST   /api/hr/v1/recruitment/plan-requests/{id}/approve

硬规则：
- tenant fail-closed 403（无上下文）；权限 hr04.plan.*。
- approve 必须事务重查 HR02 额度（PlanService）。
- 错误信封统一。
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.utils import timezone
from django.utils.dateparse import parse_date

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    make_hr04_context,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.constants import (
    NeedType,
    PlanCycleStatus,
    PlanLineStatus,
    PlanRequestStatus,
)
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.selectors import plan as plan_selector
from hr_recruitment.services.plan_service import PlanService, PlanServiceError

SERVICE = PlanService()


def _effective_organization(tenant_id, organization_id):
    from hr_structure.models import HrOrganizationVersion

    today = timezone.localdate()
    return (
        HrOrganizationVersion.objects.filter(
            tenant_id=tenant_id,
            organization_id_id=organization_id,
            status="EFFECTIVE",
            validity_from__lte=today,
        )
        .filter(models.Q(validity_to__isnull=True) | models.Q(validity_to__gt=today))
        .select_related("organization_id")
        .order_by("-validity_from", "-version_no")
        .first()
    )


def _validated_plan_lines(tenant_id, lines):
    from hr_structure.models import HrPostCatalogVersion

    if not isinstance(lines, list) or not lines:
        raise PlanServiceError(
            "PLAN_REQUEST_EMPTY", "需求申请至少包含一行需求", http_status=422
        )
    today = timezone.localdate()
    validated = []
    for line in lines:
        if not isinstance(line, dict):
            raise PlanServiceError(
                "PLAN_LINE_INVALID", "需求行格式不合法", http_status=400
            )
        catalog = (
            HrPostCatalogVersion.objects.filter(
                tenant_id=tenant_id,
                catalog_id_id=line.get("post_catalog_id"),
                status="ACTIVE",
                validity_from__lte=today,
            )
            .filter(models.Q(validity_to__isnull=True) | models.Q(validity_to__gt=today))
            .select_related("catalog_id")
            .order_by("-validity_from", "-version_no")
            .first()
        )
        if catalog is None:
            raise PlanServiceError(
                "PLAN_POST_CATALOG_NOT_FOUND",
                "请选择当前学校有效岗位目录",
                http_status=400,
            )
        headcount = int(line.get("requested_headcount", 0))
        if not 1 <= headcount <= 1_000_000:
            raise PlanServiceError(
                "PLAN_HEADCOUNT_INVALID", "需求人数必须在 1 到 1000000 之间", http_status=400
            )
        need_type = str(line.get("need_type", NeedType.NEW) or "").upper()
        if need_type not in NeedType.values:
            raise PlanServiceError(
                "PLAN_NEED_TYPE_INVALID", "需求类型不合法", http_status=400
            )
        try:
            requested_fte = Decimal(str(line.get("requested_fte", headcount)))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PlanServiceError(
                "PLAN_FTE_INVALID", "需求 FTE 不合法", http_status=400
            ) from exc
        if not Decimal("0") < requested_fte <= Decimal("999999.99"):
            raise PlanServiceError(
                "PLAN_FTE_INVALID", "需求 FTE 必须在 0 到 999999.99 之间", http_status=400
            )
        target_date = None
        if line.get("target_onboard_date"):
            target_date = parse_date(str(line["target_onboard_date"]))
            if target_date is None:
                raise PlanServiceError(
                    "PLAN_TARGET_DATE_INVALID", "计划到岗日期不合法", http_status=400
                )
        validated.append(
            {
                "catalog": catalog,
                "need_type": need_type,
                "requested_headcount": headcount,
                "requested_fte": requested_fte,
                "target_onboard_date": target_date,
                "reason": str(line.get("reason", "") or "").strip(),
            }
        )
    return validated


def _write_plan_lines(*, request_record, tenant_id, validated_lines):
    from hr_recruitment.models import HrHiringPlanLine

    for line in validated_lines:
        catalog = line["catalog"]
        HrHiringPlanLine.objects.create(
            tenant_id=tenant_id,
            request_id=request_record,
            post_catalog_id=catalog.catalog_id_id,
            post_catalog_name=catalog.name,
            need_type=line["need_type"],
            requested_headcount=line["requested_headcount"],
            requested_fte=line["requested_fte"],
            target_onboard_date=line["target_onboard_date"],
            reason=line["reason"],
            status=PlanLineStatus.REQUESTED,
        )


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

    if isinstance(exc, json.JSONDecodeError):
        return error(request, "INVALID_JSON", "请求体不是有效 JSON", 400)
    if isinstance(exc, (ValueError, TypeError, InvalidOperation)):
        return error(request, "INVALID_PAYLOAD", "请求字段格式不合法", 400)
    if isinstance(exc, ObjectDoesNotExist):
        return error(request, "NOT_FOUND", "资源不存在", 404)
    if isinstance(exc, Hr04ApiError):
        return error(request, exc.code, exc.message, exc.status_code, exc.details)
    if isinstance(exc, PlanServiceError):
        return error(request, exc.code, exc.message, exc.http_status)
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def list_plans(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.view")):
        return error(request, "PERMISSION_DENIED", "无查看年度用人计划权限", 403)
    try:
        data = plan_selector.list_plan_cycles(
            tenant_id=ctx.tenant_id,
            year=request.GET.get("year"),
            status=request.GET.get("status"),
        )
        return ok(request, {"cycles": data})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def plan_setup_options(request):
    """Return tenant-scoped HR02 authorities used by the plan authoring UI."""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.view")):
        return error(request, "PERMISSION_DENIED", "无查看年度用人计划权限", 403)
    from hr_structure.models import HrOrganizationVersion, HrPostCatalogVersion

    today = timezone.localdate()
    organizations = (
        HrOrganizationVersion.objects.filter(
            tenant_id=ctx.tenant_id,
            status="EFFECTIVE",
            validity_from__lte=today,
        )
        .filter(models.Q(validity_to__isnull=True) | models.Q(validity_to__gt=today))
        .select_related("organization_id")
        .order_by("sort_order", "name")
    )
    catalogs = (
        HrPostCatalogVersion.objects.filter(
            tenant_id=ctx.tenant_id,
            status="ACTIVE",
            validity_from__lte=today,
        )
        .filter(models.Q(validity_to__isnull=True) | models.Q(validity_to__gt=today))
        .select_related("catalog_id")
        .order_by("name", "-version_no")
    )
    return ok(
        request,
        {
            "organizations": [
                {
                    "id": item.organization_id_id,
                    "name": item.name,
                    "code": item.organization_id.stable_code,
                }
                for item in organizations
            ],
            "postCatalogs": [
                {
                    "id": item.catalog_id_id,
                    "name": item.name,
                    "code": item.catalog_id.stable_code,
                    "category": item.category,
                }
                for item in catalogs
            ],
        },
    )


@require_http_methods(["POST"])
def create_plan(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.create")):
        return error(request, "PERMISSION_DENIED", "无创建年度用人计划权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        year = int(body.get("year"))
        title = str(body.get("title", "") or "").strip()
        start_date = parse_date(str(body.get("start_date", "") or ""))
        if not 2000 <= year <= 2200 or not title or len(title) > 200 or start_date is None:
            raise PlanServiceError(
                "PLAN_CYCLE_INPUT_INVALID",
                "年度、计划名称或启动日期不合法",
                http_status=400,
            )
        cycle = SERVICE.create_cycle(
            tenant_id=ctx.tenant_id,
            year=year,
            title=title,
            start_date=start_date,
            actor=str(request.user.id),
        )
        return ok(request, {"id": str(cycle.id)}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def plan_detail(request, cycle_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.view")):
        return error(request, "PERMISSION_DENIED", "无查看年度用人计划权限", 403)
    data = plan_selector.list_plan_requests(
        tenant_id=ctx.tenant_id,
        cycle_id=cycle_id,
        status=request.GET.get("status"),
        organization_id=request.GET.get("organization_id"),
        page=int(request.GET.get("page", 1)),
        page_size=int(request.GET.get("page_size", 20)),
    )
    return ok(request, data)


@require_POST
def plan_submit(request, cycle_id):
    """周期级提交：该周期内全部 DRAFT 需求请求 → SUBMITTED，周期状态迁移。"""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.create")):
        return error(request, "PERMISSION_DENIED", "无提交权限", 403)
    try:
        from django.db import transaction as db_transaction

        from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanRequest

        cycle = HrHiringPlanCycle.objects.filter(
            tenant_id=ctx.tenant_id, id=cycle_id
        ).first()
        if cycle is None:
            return error(request, "PLAN_CYCLE_NOT_FOUND", "计划周期不存在", 404)
        with db_transaction.atomic():
            requests = list(
                HrHiringPlanRequest.objects.select_for_update().filter(
                    tenant_id=ctx.tenant_id, cycle_id=cycle, status=PlanRequestStatus.DRAFT
                )
            )
            if not requests:
                return error(request, "NO_DRAFT_REQUEST", "该周期没有待提交的需求", 422)
            for req in requests:
                SERVICE.submit(str(req.id), tenant_id=ctx.tenant_id, actor=str(request.user.id))
            cycle.status = PlanCycleStatus.SUBMITTED
            cycle.version += 1
            cycle.save(update_fields=["status", "version"])
        return ok(
            request,
            {"cycle_id": str(cycle.id), "submitted_requests": len(requests), "status": cycle.status},
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def plan_approve(request, cycle_id):
    """周期级批准：只批该周期内 UNDER_SCHOOL_APPROVAL / PARTIALLY_APPROVED 的需求，整体事务。"""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.approve")):
        return error(request, "PERMISSION_DENIED", "无批准年度用人计划权限", 403)
    try:
        from django.db import transaction as db_transaction

        from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanRequest

        cycle = HrHiringPlanCycle.objects.filter(
            tenant_id=ctx.tenant_id, id=cycle_id
        ).first()
        if cycle is None:
            return error(request, "PLAN_CYCLE_NOT_FOUND", "计划周期不存在", 404)
        request_ids = list(
            HrHiringPlanRequest.objects.filter(
                tenant_id=ctx.tenant_id,
                cycle_id=cycle_id,
                status__in=[
                    PlanRequestStatus.UNDER_SCHOOL_APPROVAL,
                    PlanRequestStatus.PARTIALLY_APPROVED,
                ],
            ).values_list("id", flat=True)
        )
        if not request_ids:
            return error(request, "NO_REQUEST_TO_APPROVE", "该周期没有待批准的请求", 422)
        with db_transaction.atomic():
            approved = []
            for rid in request_ids:
                req = SERVICE.approve(rid, tenant_id=ctx.tenant_id, actor=str(request.user.id))
                approved.append({"id": str(req.id), "status": req.status})
            cycle.status = (
                PlanCycleStatus.APPROVED
                if all(item["status"] == PlanRequestStatus.APPROVED for item in approved)
                else PlanCycleStatus.PARTIALLY_APPROVED
            )
            cycle.version += 1
            cycle.save(update_fields=["status", "version"])
        return ok(request, {"approved": approved, "status": cycle.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_plan_request(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.create")):
        return error(request, "PERMISSION_DENIED", "无创建需求权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanRequest

        cycle = HrHiringPlanCycle.objects.filter(
            tenant_id=ctx.tenant_id, id=body.get("cycle_id")
        ).first()
        if not cycle:
            return error(request, "PLAN_CYCLE_NOT_FOUND", "计划周期不存在", 404)
        if cycle.status not in {PlanCycleStatus.DRAFT, PlanCycleStatus.RETURNED}:
            return error(request, "PLAN_CYCLE_NOT_EDITABLE", "当前计划周期不可新增需求", 409)
        organization = _effective_organization(
            ctx.tenant_id, body.get("organization_id")
        )
        if organization is None:
            return error(request, "PLAN_ORGANIZATION_NOT_FOUND", "请选择当前学校有效组织", 400)
        validated_lines = _validated_plan_lines(ctx.tenant_id, body.get("lines", []))
        with transaction.atomic():
            req = HrHiringPlanRequest.objects.create(
                tenant_id=ctx.tenant_id,
                cycle_id=cycle,
                organization_id=organization.organization_id_id,
                organization_name=organization.name,
                requested_by=str(request.user.id),
                created_by=str(request.user.id),
            )
            _write_plan_lines(
                request_record=req,
                tenant_id=ctx.tenant_id,
                validated_lines=validated_lines,
            )
            req.total_requested = sum(
                line["requested_headcount"] for line in validated_lines
            )
            req.save(update_fields=["total_requested"])
        return ok(request, {"id": str(req.id)}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["GET", "PATCH"])
def plan_request_detail(request, request_id):
    """Read a demand or replace its editable content after a return."""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    permission = "hr04.plan.view" if request.method == "GET" else "hr04.plan.create"
    if not (request.user.is_superuser or request.user.has_perm(permission)):
        return error(request, "PERMISSION_DENIED", "无查看或修改用人需求权限", 403)
    if request.method == "GET":
        data = plan_selector.get_plan_request(
            tenant_id=ctx.tenant_id, request_id=request_id
        )
        if data is None:
            return error(request, "PLAN_REQUEST_NOT_FOUND", "需求申请不存在", 404)
        return ok(request, data)
    try:
        body = json.loads(request.body or b"{}")
        expected_version = int(body.get("version"))
        organization = _effective_organization(
            ctx.tenant_id, body.get("organization_id")
        )
        if organization is None:
            return error(
                request,
                "PLAN_ORGANIZATION_NOT_FOUND",
                "请选择当前学校有效组织",
                400,
            )
        validated_lines = _validated_plan_lines(
            ctx.tenant_id, body.get("lines", [])
        )
        from hr_recruitment.models import HrHiringPlanLine, HrHiringPlanRequest
        from hr_recruitment.services.audit_service import audit_event

        with transaction.atomic():
            req = (
                HrHiringPlanRequest.objects.select_for_update()
                .select_related("cycle_id")
                .filter(tenant_id=ctx.tenant_id, id=request_id)
                .first()
            )
            if req is None:
                return error(
                    request, "PLAN_REQUEST_NOT_FOUND", "需求申请不存在", 404
                )
            if req.status not in {
                PlanRequestStatus.DRAFT,
                PlanRequestStatus.RETURNED,
            }:
                return error(
                    request,
                    "PLAN_REQUEST_NOT_EDITABLE",
                    "只有草稿或已退回需求可以修改",
                    409,
                )
            if req.version != expected_version:
                return error(
                    request,
                    "PLAN_REQUEST_VERSION_CONFLICT",
                    "需求已被其他人修改，请刷新后重试",
                    409,
                    {"currentVersion": req.version},
                )
            before = {
                "organizationId": req.organization_id,
                "totalRequested": req.total_requested,
                "version": req.version,
            }
            HrHiringPlanLine.objects.filter(
                tenant_id=ctx.tenant_id, request_id=req
            ).delete()
            req.organization_id = organization.organization_id_id
            req.organization_name = organization.name
            req.total_requested = sum(
                line["requested_headcount"] for line in validated_lines
            )
            req.total_approved = 0
            req.approved_at = None
            req.version += 1
            req.save(
                update_fields=[
                    "organization_id",
                    "organization_name",
                    "total_requested",
                    "total_approved",
                    "approved_at",
                    "version",
                ]
            )
            _write_plan_lines(
                request_record=req,
                tenant_id=ctx.tenant_id,
                validated_lines=validated_lines,
            )
            audit_event(
                tenant_id=ctx.tenant_id,
                event_type="PLAN_REQUEST_UPDATED",
                business_object="HrHiringPlanRequest",
                business_object_id=str(req.id),
                actor_id=str(request.user.id),
                action="UPDATE",
                summary=f"需求申请补正：{req.organization_name}",
                before=before,
                after={
                    "organizationId": req.organization_id,
                    "totalRequested": req.total_requested,
                    "version": req.version,
                },
            )
        return ok(
            request,
            plan_selector.get_plan_request(
                tenant_id=ctx.tenant_id, request_id=request_id
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def plan_request_start_review(request, request_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.approve")):
        return error(request, "PERMISSION_DENIED", "无计划审核权限", 403)
    try:
        with transaction.atomic():
            req = SERVICE.start_hr_review(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
            req.cycle_id.status = PlanCycleStatus.UNDER_HR_REVIEW
            req.cycle_id.version += 1
            req.cycle_id.save(update_fields=["status", "version"])
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def plan_request_submit_to_school(request, request_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.approve")):
        return error(request, "PERMISSION_DENIED", "无提交学校审批权限", 403)
    try:
        with transaction.atomic():
            req = SERVICE.submit_to_school(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
            req.cycle_id.status = PlanCycleStatus.UNDER_SCHOOL_APPROVAL
            req.cycle_id.version += 1
            req.cycle_id.save(update_fields=["status", "version"])
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def plan_request_submit(request, request_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.create")):
        return error(request, "PERMISSION_DENIED", "无提交权限", 403)
    try:
        with transaction.atomic():
            req = SERVICE.submit(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
            req.cycle_id.status = (
                PlanCycleStatus.RESUBMITTED
                if req.status == PlanRequestStatus.RESUBMITTED
                else PlanCycleStatus.SUBMITTED
            )
            req.cycle_id.version += 1
            req.cycle_id.save(update_fields=["status", "version"])
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def plan_request_return(request, request_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.approve")):
        return error(request, "PERMISSION_DENIED", "无退回权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        with transaction.atomic():
            req = SERVICE.return_to_college(
                request_id, tenant_id=ctx.tenant_id, reason=body.get("reason", ""), actor=str(request.user.id)
            )
            req.cycle_id.status = PlanCycleStatus.RETURNED
            req.cycle_id.version += 1
            req.cycle_id.save(update_fields=["status", "version"])
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def plan_request_approve(request, request_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.plan.approve")):
        return error(request, "PERMISSION_DENIED", "无批准权限", 403)
    try:
        from hr_recruitment.models import HrHiringPlanRequest

        with transaction.atomic():
            req = SERVICE.approve(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
            remaining = HrHiringPlanRequest.objects.filter(
                tenant_id=ctx.tenant_id,
                cycle_id=req.cycle_id,
            ).exclude(status=PlanRequestStatus.APPROVED)
            req.cycle_id.status = (
                PlanCycleStatus.APPROVED
                if not remaining.exists()
                else PlanCycleStatus.PARTIALLY_APPROVED
            )
            req.cycle_id.version += 1
            req.cycle_id.save(update_fields=["status", "version"])
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
