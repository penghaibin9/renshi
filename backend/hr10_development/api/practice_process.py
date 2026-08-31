"""
hr10_development/api/practice_process.py

实践过程/成果 API（总册 §135）。
"""

import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import DevelopmentErrorCode, OutputType, OutputVerificationStatus
from hr10_development.models.practice_process import (
    HrEnterprisePracticeActivity,
    HrEnterprisePracticeEvidence,
    HrEnterpriseMentorFeedback,
    HrPracticeSchoolEvaluation,
    HrEnterprisePracticeEvaluation,
    HrDevelopmentOutput,
)
from hr10_development.services.practice_process_service import PracticeProcessService
from hr10_development.services.risk_service import RiskService
from hr10_development.permissions import require_hr10_permission


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def add_activity(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/activities"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    activity = HrEnterprisePracticeActivity.objects.create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        activity_date=body["activityDate"],
        activity_type=body["activityType"],
        scene_id=body.get("sceneId"),
        task_code=body.get("taskCode", ""),
        start_at=body.get("startAt"),
        end_at=body.get("endAt"),
        duration_minutes=body.get("durationMinutes"),
        title=body.get("title", ""),
        summary=body.get("summary", ""),
        source=body.get("source", "SELF"),
        status="DRAFT",
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )

    # 未来时间戳检测
    from datetime import date
    if RiskService.detect_future_timestamp(activity.activity_date):
        RiskService.open_risk_case(
            tenant_id=tenant_id,
            risk_type="SCHEDULE_CONFLICT",
            severity="LOW",
            source_case_type="HrEnterprisePracticeActivity",
            source_case_id=activity.id,
        )

    return JsonResponse(success({"id": str(activity.id), "status": activity.status}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def add_evidence(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/evidence"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    evidence = HrEnterprisePracticeEvidence.objects.create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        activity_id=body.get("activityId"),
        evidence_type=body["evidenceType"],
        document_id=body.get("documentId", ""),
        external_ref=body.get("externalRef", ""),
        source=body.get("source", "SELF"),
        submitted_by=request.user.id if request.user.is_authenticated else None,
        verification_status="SELF_REPORTED",
        content_hash=body.get("contentHash", ""),
        sensitivity=body.get("sensitivity", "INTERNAL"),
    )

    # 重复证据检测
    if evidence.content_hash:
        if RiskService.detect_duplicate_evidence(tenant_id, evidence.content_hash, assignment_id):
            RiskService.open_risk_case(
                tenant_id=tenant_id,
                risk_type="DUPLICATE_EVIDENCE",
                severity="MEDIUM",
                source_case_type="HrEnterprisePracticeEvidence",
                source_case_id=evidence.id,
            )

    return JsonResponse(success({"id": str(evidence.id), "status": evidence.verification_status}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def submit_mentor_feedback(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/mentor-feedback"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    feedback = HrEnterpriseMentorFeedback.objects.create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        mentor_id=body["mentorId"],
        rubric_version_id=body.get("rubricVersionId", ""),
        ratings_json=body.get("ratingsJson", {}),
        strengths=body.get("strengths", ""),
        gaps=body.get("gaps", ""),
        incident_flags=body.get("incidentFlags", ""),
        recommendation=body.get("recommendation", ""),
        submitted_at=datetime.now(timezone.utc),
        revision_no=0,
    )
    return JsonResponse(success({"id": str(feedback.id)}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.evaluation.manage")
def submit_school_evaluation(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/school-evaluation"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    eval_obj = HrPracticeSchoolEvaluation.objects.create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        evaluator_id=request.user.id if request.user.is_authenticated else 0,
        rubric_version_id=body.get("rubricVersionId", ""),
        evidence_package_id=body.get("evidencePackageId", ""),
        ratings_json=body.get("ratingsJson", {}),
        completion_recommendation=body.get("completionRecommendation", "PENDING"),
        concerns=body.get("concerns", ""),
        submitted_at=datetime.now(timezone.utc),
        revision_no=0,
    )
    return JsonResponse(success({"id": str(eval_obj.id)}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def submit_completion(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/submit-completion"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    from hr10_development.models.practice_models import HrEnterprisePracticeAssignment
    assignment = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not assignment:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)

    precheck = PracticeProcessService.completion_precheck(assignment)
    return JsonResponse(success(precheck))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.evaluation.manage")
def finalize_evaluation(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/finalize"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    from hr10_development.models.practice_models import HrEnterprisePracticeAssignment
    assignment = HrEnterprisePracticeAssignment.objects.filter(id=assignment_id, tenant_id=tenant_id).first()
    if not assignment:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)

    evaluation, _ = HrEnterprisePracticeEvaluation.objects.update_or_create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        defaults={
            "project_version_id": body.get("projectVersionId", 0),
            "enterprise_evaluation_ref": body.get("enterpriseEvaluationRef", ""),
            "school_evaluation_ref": body.get("schoolEvaluationRef", ""),
            "completion_status": body.get("completionStatus", "PASS"),
            "verified_hours": body.get("verifiedHours", 0),
            "verified_days": body.get("verifiedDays", 0),
            "rubric_result_json": body.get("rubricResultJson", {}),
            "final_comment": body.get("finalComment", ""),
            "decided_by": request.user.id if request.user.is_authenticated else None,
            "decided_at": datetime.now(timezone.utc),
        },
    )

    # 更新 assignment 实际核验时长
    assignment.actual_verified_hours = body.get("verifiedHours", assignment.actual_verified_hours)
    assignment.actual_verified_days = body.get("verifiedDays", assignment.actual_verified_days)
    assignment.assignment_status = "COMPLETED"
    assignment.completed_at = datetime.now(timezone.utc)
    assignment.save(update_fields=[
        "actual_verified_hours", "actual_verified_days", "assignment_status", "completed_at", "updated_at",
    ])

    return JsonResponse(success({"id": str(evaluation.id), "completionStatus": evaluation.completion_status}))


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def create_output(request):
    """POST /api/v1/hr/development/development-outputs"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)

    output = HrDevelopmentOutput.objects.create(
        tenant_id=tenant_id,
        staff_master_id=body["staffMasterId"],
        source_activity_type=body.get("sourceActivityType", ""),
        source_case_id=body.get("sourceCaseId", 0),
        output_type=body.get("outputType", OutputType.OTHER),
        title=body["title"],
        description=body.get("description", ""),
        evidence_refs=body.get("evidenceRefs", []),
        external_authority_ref=body.get("externalAuthorityRef", ""),
        verification_status=OutputVerificationStatus.SELF_REPORTED,
        created_by=request.user if request.user.is_authenticated else None,
        updated_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse(success({"id": str(output.id), "status": output.verification_status}), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@require_hr10_permission("hr.development.output.verify")
def verify_output(request, output_id):
    """POST /api/v1/hr/development/development-outputs/{id}/verify"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        body = {}

    output = HrDevelopmentOutput.objects.filter(id=output_id, tenant_id=tenant_id).first()
    if not output:
        return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "成果不存在"), status=404)

    output.verification_status = body.get("verificationStatus", "VERIFIED")
    output.verified_by = request.user.id if request.user.is_authenticated else None
    output.verified_at = datetime.now(timezone.utc)
    output.external_authority_ref = body.get("externalAuthorityRef", output.external_authority_ref)
    output.save(update_fields=[
        "verification_status", "verified_by", "verified_at", "external_authority_ref", "updated_at",
    ])

    return JsonResponse(success({"id": str(output.id), "status": output.verification_status}))
