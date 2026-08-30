"""
hr10_development/api/requests.py

培训申请/报名 API（总册 §133）。
"""

import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, RequestLifecycleStatus
from hr10_development.models.training_request import HrTrainingRequest
from hr10_development.services.approval_service import ApprovalService
from hr10_development.services.enrollment_service import EnrollmentService, check_self_approval
from hr10_development.models.offering import HrLearningOffering
from hr10_development.models.enrollment import HrLearningEnrollment
from hr10_development.models.learning_program import HrLearningProgram
from hr_staff.models import HrStaffMaster
from hr10_development.permissions import require_hr10_permission


def _request_to_dict(r: HrTrainingRequest) -> dict:
    return {
        "id": str(r.id),
        "tenantId": r.tenant_id,
        "requestNo": r.request_no,
        "staffMasterId": r.staff_master_id,
        "requestType": r.request_type,
        "requestTypeLabel": r.get_request_type_display(),
        "programId": r.program_id,
        "offeringId": r.offering_id,
        "developmentNeedId": r.development_need_id,
        "planTargetId": r.plan_target_id,
        "estimatedCost": str(r.estimated_cost) if r.estimated_cost else None,
        "leaveRequired": r.leave_required,
        "reason": r.reason,
        "lifecycleStatus": r.lifecycle_status,
        "lifecycleStatusLabel": r.get_lifecycle_status_display(),
        "currentApprovalStep": r.current_approval_step,
        "version": r.version,
        "submittedAt": r.submitted_at.isoformat() if r.submitted_at else None,
        "createdAt": r.created_at.isoformat(),
    }


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.request.view")
def list_requests(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    qs = HrTrainingRequest.objects.filter(tenant_id=tenant_id).order_by("-created_at")
    status_filter = request.GET.get("status")
    if status_filter:
        qs = qs.filter(lifecycle_status=status_filter)
    staff_filter = request.GET.get("staffId")
    if staff_filter:
        qs = qs.filter(staff_master_id=staff_filter)
    return JsonResponse(success([_request_to_dict(r) for r in qs[:100]]))


@csrf_exempt
@require_http_methods(["GET"])
@require_hr10_permission("hr.development.request.view")
def get_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        r = HrTrainingRequest.objects.get(id=request_id, tenant_id=tenant_id)
    except HrTrainingRequest.DoesNotExist:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def create_request(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    staff_id = body.get("staffMasterId")
    if not HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        legacy_employee_id=staff_id,
    ).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "教师不存在"), status=404)
    program_id = body.get("programId")
    if program_id and not HrLearningProgram.objects.filter(id=program_id, tenant_id=tenant_id).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "培训项目不存在"), status=404)
    offering_id = body.get("offeringId")
    if offering_id and not HrLearningOffering.objects.filter(id=offering_id, tenant_id=tenant_id).exists():
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "培训班次不存在"), status=404)

    r = HrTrainingRequest.objects.create(
        tenant_id=tenant_id,
        request_no=body.get("requestNo", f"REQ-{datetime.now(timezone.utc).timestamp():.0f}"),
        staff_master_id=staff_id,
        request_type=body.get("requestType", "INTERNAL_PROGRAM"),
        program_id=program_id,
        offering_id=offering_id,
        development_need_id=body.get("developmentNeedId"),
        plan_target_id=body.get("planTargetId"),
        estimated_cost=body.get("estimatedCost"),
        funding_source_id=body.get("fundingSourceId", ""),
        leave_required=body.get("leaveRequired", False),
        reason=body.get("reason", ""),
        lifecycle_status=RequestLifecycleStatus.DRAFT,
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success(_request_to_dict(r)), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def submit_request(request, request_id):
    """提交申请 → SUBMITTED → UNDER_MANAGER_REVIEW。"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    if r.lifecycle_status != RequestLifecycleStatus.DRAFT:
        return JsonResponse(error(DevelopmentErrorCode.REQUEST_ALREADY_FINAL, "申请已提交"), status=409)

    r.lifecycle_status = RequestLifecycleStatus.UNDER_MANAGER_REVIEW
    r.current_approval_step = 1
    r.submitted_at = datetime.now(timezone.utc)
    r.version += 1
    r.save(update_fields=["lifecycle_status", "current_approval_step", "submitted_at", "version", "updated_at"])
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.approve")
def approve_request(request, request_id):
    """审批推进一步。"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)

    approver_id = request.user.id if request.user.is_authenticated else 0
    if check_self_approval(r.staff_master_id, approver_id):
        return JsonResponse(error(DevelopmentErrorCode.SELF_APPROVAL_NOT_ALLOWED, "禁止自审批"), status=403)

    result = ApprovalService.approve_step(
        request_obj=r,
        approver_id=approver_id,
        workflow_version=request.GET.get("workflowVersion", "DEFAULT_V1"),
    )
    if result.get("error"):
        return JsonResponse(error(result["error"], "禁止自审批"), status=403)
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.approve")
def return_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    ApprovalService.return_step(request_obj=r, approver_id=request.user.id if request.user.is_authenticated else 0,
                                workflow_version="DEFAULT_V1")
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.approve")
def reject_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    ApprovalService.reject(request_obj=r, approver_id=request.user.id if request.user.is_authenticated else 0,
                           workflow_version="DEFAULT_V1")
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def withdraw_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    r.lifecycle_status = RequestLifecycleStatus.WITHDRAWN
    r.version += 1
    r.save(update_fields=["lifecycle_status", "version", "updated_at"])
    return JsonResponse(success(_request_to_dict(r)))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def enroll_in_offering(request, offering_id):
    """POST /api/v1/hr/development/offerings/{id}/enroll"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}
    staff_id = body.get("staffMasterId")
    if not staff_id:
        return JsonResponse(error("MISSING_FIELD", "staffMasterId 必填"), status=400)

    offering = HrLearningOffering.objects.filter(id=offering_id, tenant_id=tenant_id).first()
    if not offering:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)

    try:
        enrollment = EnrollmentService.enroll(offering, int(staff_id), tenant_id)
    except ValueError as e:
        return JsonResponse(error(str(e), "名额已满或冲突"), status=409)

    return JsonResponse(success({"id": str(enrollment.id), "status": enrollment.enrollment_status}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def waitlist_offering(request, offering_id):
    """POST /api/v1/hr/development/offerings/{id}/waitlist"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}
    staff_id = body.get("staffMasterId")
    if not staff_id:
        return JsonResponse(error("MISSING_FIELD", "staffMasterId 必填"), status=400)
    offering = HrLearningOffering.objects.filter(id=offering_id, tenant_id=tenant_id).first()
    if not offering:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "班次不存在"), status=404)
    try:
        enrollment = EnrollmentService.waitlist(offering, int(staff_id), tenant_id)
    except ValueError as e:
        return JsonResponse(error(str(e), "候补已满"), status=409)
    return JsonResponse(success({"id": str(enrollment.id), "status": enrollment.enrollment_status}), status=201)
