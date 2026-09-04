"""
hr10_development/api/enrollments.py

报名完成/核验 API（总册 §133）。
"""

import json
from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, EnrollmentStatus
from hr10_development.models.enrollment import HrLearningEnrollment
from hr10_development.models.learning_completion import HrLearningCompletion
from hr10_development.models.offering import HrLearningOffering
from hr10_development.services.completion_service import CompletionService
from hr10_development.permissions import require_hr10_permission


def _body_object(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return body if isinstance(body, dict) else None


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def complete_enrollment(request, enrollment_id):
    """
    POST /api/v1/hr/development/enrollments/{id}/complete
    提交完成核验申请。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            enrollment = HrLearningEnrollment.objects.select_for_update().filter(
                id=enrollment_id, tenant_id=tenant_id
            ).first()
            if not enrollment:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "报名记录不存在"), status=404)
            if enrollment.enrollment_status not in {
                EnrollmentStatus.CONFIRMED,
                EnrollmentStatus.COMPLETED,
            }:
                return JsonResponse(error("ENROLLMENT_STATE_CONFLICT", "当前报名状态不能提交完成证明"), status=409)
            offering = HrLearningOffering.objects.filter(
                id=enrollment.offering_id, tenant_id=tenant_id
            ).first()
            if offering is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "培训班次不存在"), status=404)
            completion = HrLearningCompletion.objects.select_for_update().filter(
                tenant_id=tenant_id, enrollment_id=enrollment.id
            ).order_by("-id").first()
            if completion is None:
                completion = HrLearningCompletion(
                    tenant_id=tenant_id,
                    enrollment_id=enrollment.id,
                    program_version_id=offering.program_version_id,
                    completion_status="INCOMPLETE",
                    verified_hours=body.get("verifiedHours"),
                    verified_credits=body.get("verifiedCredits"),
                    score=body.get("score"),
                    verification_status="SELF_REPORTED",
                    immutable_hash="",
                )
                completion.full_clean()
                for value in (completion.verified_hours, completion.verified_credits, completion.score):
                    if value is not None and value < 0:
                        raise ValueError("完成学时、学分和成绩不能为负数")
                completion.save()
            result = CompletionService.submit_completion(
                completion=completion,
                submitted_evidence_package_id=str(body.get("evidencePackageId") or "").strip(),
            )
            completion.refresh_from_db()
    except (ValueError, TypeError, ValidationError) as exc:
        message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse(error("INVALID_REQUEST", message), status=400)
    except IntegrityError:
        return JsonResponse(error(DevelopmentErrorCode.VERSION_CONFLICT, "完成记录已由其他操作创建"), status=409)

    return JsonResponse(success({
        "completionId": str(completion.id),
        "status": result["status"],
        "completionStatus": completion.completion_status,
    }))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.completion.verify")
def verify_completion(request, enrollment_id):
    """
    POST /api/v1/hr/development/enrollments/{id}/verify-completion
    完成核验 → 满足条件则生成 DevelopmentFact。
    """
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    with transaction.atomic():
        enrollment = HrLearningEnrollment.objects.select_for_update().filter(
            id=enrollment_id, tenant_id=tenant_id
        ).first()
        if not enrollment:
            return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "报名记录不存在"), status=404)
        completion = HrLearningCompletion.objects.select_for_update().filter(
            tenant_id=tenant_id, enrollment_id=enrollment.id
        ).order_by("-id").first()
        if not completion:
            return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "完成记录不存在"), status=404)
        verification_source = body.get("verificationSource", "HR_VERIFIED")
        result = CompletionService.verify_completion(
            completion=completion,
            verifier_id=request.user.id if request.user.is_authenticated else 0,
            verification_source=verification_source,
        )
        if result["status"] == "INVALID_VERIFICATION_SOURCE":
            return JsonResponse(error("INVALID_VERIFICATION_SOURCE", "核验来源不受信任"), status=400)
        if result["status"] == "COMPLETION_REVISION_REQUIRED":
            return JsonResponse(error(DevelopmentErrorCode.COMPLETION_REVISION_REQUIRED, "已冻结完成记录必须走修订流程"), status=409)
        completion.refresh_from_db()
        if result["status"] in {"VERIFIED", "COMPLETION_ALREADY_VERIFIED"}:
            enrollment.enrollment_status = EnrollmentStatus.COMPLETED
            enrollment.completed_at = enrollment.completed_at or datetime.now(timezone.utc)
            enrollment.save(update_fields=["enrollment_status", "completed_at", "updated_at"])
    return JsonResponse(success({
        "status": result["status"],
        "factId": result.get("factId"),
        "verificationStatus": completion.verification_status,
        "immutableHash": completion.immutable_hash,
    }))
