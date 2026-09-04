"""
hr10_development/api/requests.py

培训申请/报名 API（总册 §133）。
"""

import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
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


def _approval_error_response(result):
    code = result.get("error")
    if not code:
        return None
    status = 403 if code == DevelopmentErrorCode.SELF_APPROVAL_NOT_ALLOWED else 409
    if code == DevelopmentErrorCode.NOT_FOUND:
        status = 404
    return JsonResponse(error(code, "申请当前状态不允许执行该审批操作"), status=status)


def _approver_employee_id(request):
    """Use the legacy Employee ID, matching HrTrainingRequest.staff_master_id."""
    if not request.user.is_authenticated:
        return 0
    try:
        return request.user.employee_get.id
    except (AttributeError, ObjectDoesNotExist):
        return request.user.id


def _body_object(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return body if isinstance(body, dict) else None


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


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def create_request(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        staff_id = int(body["staffMasterId"])
        with transaction.atomic():
            if not HrStaffMaster.objects.select_for_update().filter(
                tenant_id=tenant_id, legacy_employee_id=staff_id
            ).exists():
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "教师不存在"), status=404)
            program_id = body.get("programId")
            program = None
            if program_id:
                program = HrLearningProgram.objects.select_for_update().filter(
                    id=program_id, tenant_id=tenant_id,
                    lifecycle_status__in=["PUBLISHED", "ACTIVE"],
                ).first()
                if program is None:
                    return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "已发布培训项目不存在"), status=404)
            offering_id = body.get("offeringId")
            offering = None
            if offering_id:
                offering = HrLearningOffering.objects.filter(
                    id=offering_id, tenant_id=tenant_id
                ).first()
                if offering is None:
                    return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "培训班次不存在"), status=404)
                from hr10_development.models.program_version import HrLearningProgramVersion

                if not program or not HrLearningProgramVersion.objects.filter(
                    id=offering.program_version_id,
                    tenant_id=tenant_id,
                    program_id=program.id,
                ).exists():
                    return JsonResponse(error("REQUEST_PROGRAM_OFFERING_MISMATCH", "培训班次不属于所选项目"), status=409)
            r = HrTrainingRequest(
                tenant_id=tenant_id,
                request_no=str(body.get("requestNo") or f"REQ-{datetime.now(timezone.utc).timestamp():.0f}").strip(),
                staff_master_id=staff_id,
                request_type=body.get("requestType", "INTERNAL_PROGRAM"),
                program_id=program_id,
                offering_id=offering_id,
                development_need_id=body.get("developmentNeedId"),
                plan_target_id=body.get("planTargetId"),
                estimated_cost=body.get("estimatedCost"),
                funding_source_id=str(body.get("fundingSourceId") or "").strip(),
                leave_required=body.get("leaveRequired", False),
                reason=str(body.get("reason") or "").strip(),
                lifecycle_status=RequestLifecycleStatus.DRAFT,
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            r.full_clean()
            r.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse(error("INVALID_REQUEST", message), status=400)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "申请编号已存在"), status=409)
    return JsonResponse(success(_request_to_dict(r)), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
@transaction.atomic
def submit_request(request, request_id):
    """提交申请 → SUBMITTED → UNDER_MANAGER_REVIEW。"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.select_for_update().filter(
        id=request_id, tenant_id=tenant_id
    ).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    if r.lifecycle_status not in {
        RequestLifecycleStatus.DRAFT,
        RequestLifecycleStatus.RETURNED,
    }:
        return JsonResponse(error(DevelopmentErrorCode.REQUEST_ALREADY_FINAL, "申请已提交"), status=409)

    r.lifecycle_status = RequestLifecycleStatus.UNDER_MANAGER_REVIEW
    r.current_approval_step = 1
    r.submitted_at = datetime.now(timezone.utc)
    r.version += 1
    r.save(update_fields=["lifecycle_status", "current_approval_step", "submitted_at", "version", "updated_at"])
    return JsonResponse(success(_request_to_dict(r)))


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

    approver_id = _approver_employee_id(request)
    if check_self_approval(r.staff_master_id, approver_id):
        return JsonResponse(error(DevelopmentErrorCode.SELF_APPROVAL_NOT_ALLOWED, "禁止自审批"), status=403)

    workflow_version = request.POST.get("workflowVersion", "DEFAULT_V1")
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
        if not isinstance(payload, dict):
            return JsonResponse(error("INVALID_JSON", "请求体必须是对象"), status=400)
        workflow_version = payload.get("workflowVersion", "DEFAULT_V1")
    if not isinstance(workflow_version, str) or not 1 <= len(workflow_version) <= 64:
        return JsonResponse(error("INVALID_WORKFLOW_VERSION", "审批流程版本非法"), status=400)

    result = ApprovalService.approve_step(
        request_obj=r,
        approver_id=approver_id,
        workflow_version=workflow_version,
    )
    if response := _approval_error_response(result):
        return response
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.approve")
def return_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    result = ApprovalService.return_step(
        request_obj=r,
        approver_id=_approver_employee_id(request),
        workflow_version="DEFAULT_V1",
    )
    if response := _approval_error_response(result):
        return response
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.approve")
def reject_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.filter(id=request_id, tenant_id=tenant_id).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    result = ApprovalService.reject(
        request_obj=r,
        approver_id=_approver_employee_id(request),
        workflow_version="DEFAULT_V1",
    )
    if response := _approval_error_response(result):
        return response
    r.refresh_from_db()
    return JsonResponse(success(_request_to_dict(r)))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
@transaction.atomic
def withdraw_request(request, request_id):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    r = HrTrainingRequest.objects.select_for_update().filter(
        id=request_id, tenant_id=tenant_id
    ).first()
    if not r:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "申请不存在"), status=404)
    if not ApprovalService._is_reviewable(r.lifecycle_status) and r.lifecycle_status not in {
        RequestLifecycleStatus.DRAFT,
        RequestLifecycleStatus.RETURNED,
    }:
        return JsonResponse(
            error(DevelopmentErrorCode.REQUEST_ALREADY_FINAL, "申请当前状态不可撤回"),
            status=409,
        )
    r.lifecycle_status = RequestLifecycleStatus.WITHDRAWN
    r.version += 1
    r.save(update_fields=["lifecycle_status", "version", "updated_at"])
    return JsonResponse(success(_request_to_dict(r)))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def enroll_in_offering(request, offering_id):
    """POST /api/v1/hr/development/offerings/{id}/enroll"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    staff_id = body.get("staffMasterId")
    if not staff_id:
        return JsonResponse(error("MISSING_FIELD", "staffMasterId 必填"), status=400)

    try:
        offering = HrLearningOffering(id=offering_id, tenant_id=tenant_id)
        enrollment = EnrollmentService.enroll(offering, int(staff_id), tenant_id)
    except ValueError as e:
        code = str(e)
        status = 404 if code == DevelopmentErrorCode.NOT_FOUND else 409
        return JsonResponse(error(code, "报名失败：班次未开放、名额不足或记录冲突"), status=status)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.DUPLICATE_ENROLLMENT, "请勿重复报名"), status=409)

    return JsonResponse(success({"id": str(enrollment.id), "status": enrollment.enrollment_status}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.request.create")
def waitlist_offering(request, offering_id):
    """POST /api/v1/hr/development/offerings/{id}/waitlist"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    staff_id = body.get("staffMasterId")
    if not staff_id:
        return JsonResponse(error("MISSING_FIELD", "staffMasterId 必填"), status=400)
    try:
        offering = HrLearningOffering(id=offering_id, tenant_id=tenant_id)
        enrollment = EnrollmentService.waitlist(offering, int(staff_id), tenant_id)
    except ValueError as e:
        code = str(e)
        status = 404 if code == DevelopmentErrorCode.NOT_FOUND else 409
        return JsonResponse(error(code, "候补失败：候补未开放、名额不足或记录冲突"), status=status)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.DUPLICATE_ENROLLMENT, "请勿重复候补"), status=409)
    return JsonResponse(success({"id": str(enrollment.id), "status": enrollment.enrollment_status}), status=201)
