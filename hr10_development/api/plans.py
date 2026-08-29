"""
hr10_development/api/plans.py

发展计划 REST API（总册 §131）。
"""

import json
import uuid

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, PlanLifecycleStatus
from hr10_development.models.plan import HrDevelopmentPlan
from hr10_development.models.plan_version import HrDevelopmentPlanVersion
from hr10_development.services.plan_service import PlanService
from hr_staff.models import HrStaffMaster


def _plan_to_dict(plan: HrDevelopmentPlan) -> dict:
    return {
        "id": str(plan.id),
        "tenantId": plan.tenant_id,
        "planNo": plan.plan_no,
        "planType": plan.plan_type,
        "planTypeLabel": plan.get_plan_type_display(),
        "ownerOrgId": plan.owner_org_id,
        "staffMasterId": plan.staff_master_id,
        "cycleType": plan.cycle_type,
        "startDate": str(plan.start_date) if plan.start_date else None,
        "endDate": str(plan.end_date) if plan.end_date else None,
        "currentVersionId": plan.current_version_id,
        "lifecycleStatus": plan.lifecycle_status,
        "lifecycleStatusLabel": plan.get_lifecycle_status_display(),
        "approvedAt": plan.approved_at.isoformat() if plan.approved_at else None,
        "publishedAt": plan.published_at.isoformat() if plan.published_at else None,
        "version": plan.version,
        "createdAt": plan.created_at.isoformat(),
        "updatedAt": plan.updated_at.isoformat(),
    }


def _version_to_dict(v: HrDevelopmentPlanVersion) -> dict:
    return {
        "id": str(v.id),
        "tenantId": v.tenant_id,
        "planId": v.plan_id,
        "versionNo": v.version_no,
        "status": v.status,
        "statusLabel": v.get_status_display(),
        "objectivesJson": v.objectives_json,
        "populationSnapshotJson": v.population_snapshot_json,
        "budgetSnapshotJson": v.budget_snapshot_json,
        "policySnapshotJson": v.policy_snapshot_json,
        "targetSnapshotJson": v.target_snapshot_json,
        "contentHash": v.content_hash,
        "effectiveFrom": str(v.effective_from) if v.effective_from else None,
        "createdAt": v.created_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET"])
def list_plans(request):
    """GET /api/v1/hr/development/plans"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    plans = (
        HrDevelopmentPlan.objects
        .filter(tenant_id=tenant_id)
        .order_by("-created_at")
    )

    status_filter = request.GET.get("status")
    if status_filter:
        plans = plans.filter(lifecycle_status=status_filter)

    data = [_plan_to_dict(p) for p in plans[:100]]
    return JsonResponse(success(data))


@csrf_exempt
@require_http_methods(["GET"])
def get_plan(request, plan_id):
    """GET /api/v1/hr/development/plans/{planId}"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def create_plan(request):
    """POST /api/v1/hr/development/plans"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            error("INVALID_JSON", "请求体不是有效 JSON"),
            status=400,
        )

    plan_no = body.get("planNo")
    if not plan_no:
        return JsonResponse(
            error("MISSING_FIELD", "planNo 必填"), status=400
        )

    plan_type = body.get("planType", "SCHOOL")
    staff_id = body.get("staffMasterId")
    if plan_type == "INDIVIDUAL" and not HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        legacy_employee_id=staff_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "教师不存在"), status=404)

    plan = PlanService.create_plan(
        tenant_id=tenant_id,
        plan_no=plan_no,
        plan_type=plan_type,
        start_date=body.get("startDate"),
        end_date=body.get("endDate"),
        cycle_type=body.get("cycleType", "ANNUAL"),
        owner_org_id=body.get("ownerOrgId"),
        staff_master_id=staff_id if plan_type == "INDIVIDUAL" else None,
        created_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_plan_to_dict(plan)), status=201)


@csrf_exempt
@require_http_methods(["POST"])
def submit_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/submit"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if not plan.can_transition_to(PlanLifecycleStatus.READY_FOR_REVIEW):
        return JsonResponse(
            error(
                DevelopmentErrorCode.VERSION_CONFLICT,
                f"不能从 {plan.lifecycle_status} 提交审核",
            ),
            status=409,
        )

    ok = PlanService.transition(plan, PlanLifecycleStatus.READY_FOR_REVIEW,
                                actor=request.user if request.user.is_authenticated else None)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def approve_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/approve"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if plan.lifecycle_status not in [
        PlanLifecycleStatus.READY_FOR_REVIEW,
        PlanLifecycleStatus.UNDER_REVIEW,
    ]:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "计划不在审核中状态"),
            status=409,
        )

    actor = request.user if request.user.is_authenticated else None
    if plan.lifecycle_status == PlanLifecycleStatus.READY_FOR_REVIEW:
        PlanService.transition(plan, PlanLifecycleStatus.UNDER_REVIEW, actor=actor)
    ok = PlanService.transition(plan, PlanLifecycleStatus.APPROVED, actor=actor)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def publish_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/publish"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if plan.lifecycle_status != PlanLifecycleStatus.APPROVED:
        return JsonResponse(
            error(DevelopmentErrorCode.DEVELOPMENT_PLAN_NOT_PUBLISHED,
                  "计划未批准，不能发布"),
            status=409,
        )

    ok = PlanService.transition(plan, PlanLifecycleStatus.PUBLISHED,
                                actor=request.user if request.user.is_authenticated else None)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def return_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/return"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if plan.lifecycle_status != PlanLifecycleStatus.UNDER_REVIEW:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "计划不在审核中状态"),
            status=409,
        )

    ok = PlanService.transition(plan, PlanLifecycleStatus.RETURNED,
                                actor=request.user if request.user.is_authenticated else None)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def reject_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/reject"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if plan.lifecycle_status != PlanLifecycleStatus.UNDER_REVIEW:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "计划不在审核中状态"),
            status=409,
        )

    ok = PlanService.transition(plan, PlanLifecycleStatus.REJECTED,
                                actor=request.user if request.user.is_authenticated else None)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def close_plan(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/close"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    if plan.lifecycle_status not in [PlanLifecycleStatus.ACTIVE, PlanLifecycleStatus.CLOSING]:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "只能关闭执行中或关闭中的计划"),
            status=409,
        )

    ok = PlanService.transition(plan, PlanLifecycleStatus.CLOSED,
                                actor=request.user if request.user.is_authenticated else None)
    if not ok:
        return JsonResponse(
            error(DevelopmentErrorCode.VERSION_CONFLICT, "状态转换失败"),
            status=409,
        )
    return JsonResponse(success(_plan_to_dict(plan)))


@csrf_exempt
@require_http_methods(["POST"])
def create_plan_version(request, plan_id):
    """POST /api/v1/hr/development/plans/{planId}/versions"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(
            error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"),
            status=403,
        )

    try:
        plan = HrDevelopmentPlan.objects.get(id=plan_id, tenant_id=tenant_id)
    except HrDevelopmentPlan.DoesNotExist:
        return JsonResponse(
            error(DevelopmentErrorCode.NOT_FOUND, "计划不存在"),
            status=404,
        )

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            error("INVALID_JSON", "请求体不是有效 JSON"),
            status=400,
        )

    version = PlanService.create_version(
        plan=plan,
        objectives_json=body.get("objectivesJson", {}),
        population_snapshot=body.get("populationSnapshotJson", {}),
        budget_snapshot=body.get("budgetSnapshotJson", {}),
        policy_snapshot=body.get("policySnapshotJson", {}),
        target_snapshot=body.get("targetSnapshotJson", {}),
        effective_from=body.get("effectiveFrom"),
        created_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_version_to_dict(version)), status=201)
