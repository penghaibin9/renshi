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

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    make_hr04_context,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.constants import PlanCycleStatus, PlanRequestStatus
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.selectors import plan as plan_selector
from hr_recruitment.services.plan_service import PlanService, PlanServiceError

SERVICE = PlanService()


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

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
        cycle = SERVICE.create_cycle(
            tenant_id=ctx.tenant_id,
            year=int(body.get("year")),
            title=body.get("title", ""),
            start_date=body.get("start_date"),
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
        targets = plan_selector.list_plan_requests(
            tenant_id=ctx.tenant_id,
            cycle_id=cycle_id,
            status__in=[PlanRequestStatus.UNDER_SCHOOL_APPROVAL, PlanRequestStatus.PARTIALLY_APPROVED],
        )
        request_ids = [r["id"] for r in targets["items"]]
        if not request_ids:
            return error(request, "NO_REQUEST_TO_APPROVE", "该周期没有待批准的请求", 422)
        with db_transaction.atomic():
            approved = []
            for rid in request_ids:
                req = SERVICE.approve(rid, tenant_id=ctx.tenant_id, actor=str(request.user.id))
                approved.append({"id": str(req.id), "status": req.status})
        return ok(request, {"approved": approved})
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
        from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanLine, HrHiringPlanRequest

        cycle = HrHiringPlanCycle.objects.filter(
            tenant_id=ctx.tenant_id, id=body.get("cycle_id")
        ).first()
        if not cycle:
            return error(request, "PLAN_CYCLE_NOT_FOUND", "计划周期不存在", 404)
        req = HrHiringPlanRequest.objects.create(
            tenant_id=ctx.tenant_id,
            cycle_id=cycle,
            organization_id=body.get("organization_id"),
            organization_name=body.get("organization_name", ""),
            requested_by=body.get("requested_by", ""),
        )
        for line in body.get("lines", []):
            HrHiringPlanLine.objects.create(
                tenant_id=ctx.tenant_id,
                request_id=req,
                post_catalog_id=line.get("post_catalog_id"),
                post_catalog_name=line.get("post_catalog_name", ""),
                need_type=line.get("need_type", "NEW"),
                requested_headcount=int(line.get("requested_headcount", 0)),
                requested_fte=line.get("requested_fte", 0),
                target_onboard_date=line.get("target_onboard_date"),
                reason=line.get("reason", ""),
            )
        req.total_requested = sum(l.requested_headcount for l in req.lines.all())
        req.save(update_fields=["total_requested"])
        return ok(request, {"id": str(req.id)}, status=201)
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
        req = SERVICE.submit(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
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
        req = SERVICE.return_to_college(
            request_id, tenant_id=ctx.tenant_id, reason=body.get("reason", ""), actor=str(request.user.id)
        )
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
        req = SERVICE.approve(request_id, tenant_id=ctx.tenant_id, actor=str(request.user.id))
        return ok(request, {"id": str(req.id), "status": req.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
