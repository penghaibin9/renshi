"""
hr10_development/api/enrollments.py

报名完成/核验 API（总册 §133）。
"""

import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, EnrollmentStatus
from hr10_development.models.enrollment import HrLearningEnrollment
from hr10_development.models.learning_completion import HrLearningCompletion
from hr10_development.models.offering import HrLearningOffering
from hr10_development.services.completion_service import CompletionService
from hr10_development.permissions import require_hr10_permission


@csrf_exempt
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
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    enrollment = HrLearningEnrollment.objects.filter(id=enrollment_id, tenant_id=tenant_id).first()
    if not enrollment:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "报名记录不存在"), status=404)

    completion, _ = HrLearningCompletion.objects.get_or_create(
        tenant_id=tenant_id,
        enrollment_id=enrollment.id,
        defaults={
            "program_version_id": body.get("programVersionId", 0),
            "completion_status": "INCOMPLETE",
            "verified_hours": body.get("verifiedHours"),
            "verified_credits": body.get("verifiedCredits"),
            "score": body.get("score"),
            "verification_status": "SELF_REPORTED",
            "immutable_hash": "",
        },
    )

    result = CompletionService.submit_completion(
        completion=completion,
        submitted_evidence_package_id=body.get("evidencePackageId", ""),
    )
    completion.refresh_from_db()

    enrollment.enrollment_status = EnrollmentStatus.COMPLETED
    enrollment.completed_at = datetime.now(timezone.utc)
    enrollment.save(update_fields=["enrollment_status", "completed_at", "updated_at"])

    return JsonResponse(success({
        "completionId": str(completion.id),
        "status": result["status"],
        "completionStatus": completion.completion_status,
    }))


@csrf_exempt
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
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    enrollment = HrLearningEnrollment.objects.filter(id=enrollment_id, tenant_id=tenant_id).first()
    if not enrollment:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "报名记录不存在"), status=404)

    completion = HrLearningCompletion.objects.filter(
        tenant_id=tenant_id, enrollment_id=enrollment.id,
    ).order_by("-id").first()
    if not completion:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "完成记录不存在"), status=404)

    verification_source = body.get("verificationSource", "HR_VERIFIED")
    result = CompletionService.verify_completion(
        completion=completion,
        verifier_id=request.user.id if request.user.is_authenticated else 0,
        verification_source=verification_source,
    )
    completion.refresh_from_db()
    return JsonResponse(success({
        "status": result["status"],
        "factId": result.get("factId"),
        "verificationStatus": completion.verification_status,
        "immutableHash": completion.immutable_hash,
    }))
