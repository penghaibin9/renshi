"""
hr10_development/api/practice_process.py

实践过程/成果 API（总册 §135）。
"""

import json
from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from hr10_development.api.envelope import success, error
from hr10_development.constants import (
    AssignmentStatus,
    DevelopmentErrorCode,
    OutputType,
    OutputVerificationStatus,
    PracticeEvaluationStatus,
)
from hr10_development.models.practice_models import HrEnterprisePracticeAssignment
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
from hr_staff.models import HrStaffMaster


def _body_object(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _locked_assignment(tenant_id, assignment_id):
    return HrEnterprisePracticeAssignment.objects.select_for_update().filter(
        id=assignment_id,
        tenant_id=tenant_id,
    ).first()


def _invalid(exc):
    if isinstance(exc, KeyError):
        message = f"缺少必填参数: {exc.args[0]}"
    elif isinstance(exc, ValidationError):
        message = "; ".join(exc.messages)
    else:
        message = str(exc)
    return JsonResponse(error("INVALID_REQUEST", message), status=400)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def add_activity(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/activities"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            assignment = _locked_assignment(tenant_id, assignment_id)
            if assignment is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
            if assignment.assignment_status != AssignmentStatus.IN_PROGRESS:
                return JsonResponse(error("PRACTICE_STATE_CONFLICT", "只有进行中的实践可以记录活动"), status=409)
            activity = HrEnterprisePracticeActivity(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
                activity_date=body["activityDate"],
                activity_type=body["activityType"],
                scene_id=body.get("sceneId"),
                task_code=str(body.get("taskCode") or "").strip(),
                start_at=body.get("startAt"),
                end_at=body.get("endAt"),
                duration_minutes=body.get("durationMinutes"),
                title=str(body.get("title") or "").strip(),
                summary=str(body.get("summary") or "").strip(),
                source=str(body.get("source") or "SELF").strip(),
                status="DRAFT",
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            activity.full_clean()
            activity.save()

            if RiskService.detect_future_timestamp(activity.activity_date):
                RiskService.open_risk_case(
                    tenant_id=tenant_id,
                    risk_type="SCHEDULE_CONFLICT",
                    severity="LOW",
                    source_case_type="HrEnterprisePracticeActivity",
                    source_case_id=activity.id,
                )
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)

    return JsonResponse(success({"id": str(activity.id), "status": activity.status}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def add_evidence(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/evidence"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            assignment = _locked_assignment(tenant_id, assignment_id)
            if assignment is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
            if assignment.assignment_status not in {
                AssignmentStatus.IN_PROGRESS,
                AssignmentStatus.SUSPENDED,
                AssignmentStatus.COMPLETION_REVIEW,
            }:
                return JsonResponse(error("PRACTICE_STATE_CONFLICT", "当前实践状态不能补充证据"), status=409)
            activity_id = body.get("activityId")
            if activity_id and not HrEnterprisePracticeActivity.objects.filter(
                id=activity_id,
                tenant_id=tenant_id,
                assignment_id=assignment.id,
            ).exists():
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "实践活动不存在"), status=404)
            evidence = HrEnterprisePracticeEvidence(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
                activity_id=activity_id,
                evidence_type=body["evidenceType"],
                document_id=str(body.get("documentId") or "").strip(),
                external_ref=str(body.get("externalRef") or "").strip(),
                source=str(body.get("source") or "SELF").strip(),
                submitted_by=request.user.id if request.user.is_authenticated else None,
                verification_status=OutputVerificationStatus.SELF_REPORTED,
                content_hash=str(body.get("contentHash") or "").strip(),
                sensitivity=str(body.get("sensitivity") or "INTERNAL").strip(),
            )
            evidence.full_clean()
            evidence.save()

            if evidence.content_hash and RiskService.detect_duplicate_evidence(
                tenant_id, evidence.content_hash, assignment.id
            ):
                RiskService.open_risk_case(
                    tenant_id=tenant_id,
                    risk_type="DUPLICATE_EVIDENCE",
                    severity="MEDIUM",
                    source_case_type="HrEnterprisePracticeEvidence",
                    source_case_id=evidence.id,
                )
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)

    return JsonResponse(success({"id": str(evidence.id), "status": evidence.verification_status}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def submit_mentor_feedback(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/mentor-feedback"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            assignment = _locked_assignment(tenant_id, assignment_id)
            if assignment is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
            if assignment.assignment_status not in {
                AssignmentStatus.IN_PROGRESS,
                AssignmentStatus.SUSPENDED,
                AssignmentStatus.COMPLETION_REVIEW,
            }:
                return JsonResponse(error("PRACTICE_STATE_CONFLICT", "当前实践状态不能提交导师评价"), status=409)
            if int(body["mentorId"]) != assignment.enterprise_mentor_id:
                return JsonResponse(error("PRACTICE_MENTOR_MISMATCH", "导师不属于该派出记录"), status=409)
            feedback = HrEnterpriseMentorFeedback(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
                mentor_id=assignment.enterprise_mentor_id,
                rubric_version_id=str(body.get("rubricVersionId") or "").strip(),
                ratings_json=body.get("ratingsJson", {}),
                strengths=str(body.get("strengths") or "").strip(),
                gaps=str(body.get("gaps") or "").strip(),
                incident_flags=str(body.get("incidentFlags") or "").strip(),
                recommendation=str(body.get("recommendation") or "").strip(),
                submitted_at=datetime.now(timezone.utc),
                revision_no=0,
            )
            feedback.full_clean()
            feedback.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    return JsonResponse(success({"id": str(feedback.id)}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.evaluation.manage")
def submit_school_evaluation(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/school-evaluation"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            assignment = _locked_assignment(tenant_id, assignment_id)
            if assignment is None:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
            if assignment.assignment_status not in {
                AssignmentStatus.IN_PROGRESS,
                AssignmentStatus.SUSPENDED,
                AssignmentStatus.COMPLETION_REVIEW,
            }:
                return JsonResponse(error("PRACTICE_STATE_CONFLICT", "当前实践状态不能提交学校评价"), status=409)
            eval_obj = HrPracticeSchoolEvaluation(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
                evaluator_id=request.user.id if request.user.is_authenticated else 0,
                rubric_version_id=str(body.get("rubricVersionId") or "").strip(),
                evidence_package_id=str(body.get("evidencePackageId") or "").strip(),
                ratings_json=body.get("ratingsJson", {}),
                completion_recommendation=body.get("completionRecommendation", "PENDING"),
                concerns=str(body.get("concerns") or "").strip(),
                submitted_at=datetime.now(timezone.utc),
                revision_no=0,
            )
            eval_obj.full_clean()
            eval_obj.save()
    except (ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    return JsonResponse(success({"id": str(eval_obj.id)}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def submit_completion(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/submit-completion"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)

    with transaction.atomic():
        assignment = _locked_assignment(tenant_id, assignment_id)
        if not assignment:
            return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
        if assignment.assignment_status == AssignmentStatus.COMPLETED:
            return JsonResponse(error("PRACTICE_STATE_CONFLICT", "该实践已完成"), status=409)
        if assignment.assignment_status not in {
            AssignmentStatus.IN_PROGRESS,
            AssignmentStatus.COMPLETION_REVIEW,
        }:
            return JsonResponse(error("PRACTICE_STATE_CONFLICT", "当前状态不能提交完成核验"), status=409)
        precheck = PracticeProcessService.completion_precheck(assignment)
        if precheck["status"] == "PASS" and assignment.assignment_status != AssignmentStatus.COMPLETION_REVIEW:
            assignment.assignment_status = AssignmentStatus.COMPLETION_REVIEW
            assignment.save(update_fields=["assignment_status", "updated_at"])
        precheck["assignmentStatus"] = assignment.assignment_status
    return JsonResponse(success(precheck))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.evaluation.manage")
def finalize_evaluation(request, assignment_id):
    """POST /api/v1/hr/development/practice-assignments/{id}/finalize"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        with transaction.atomic():
            assignment = _locked_assignment(tenant_id, assignment_id)
            if not assignment:
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "派出记录不存在"), status=404)
            if assignment.assignment_status != AssignmentStatus.COMPLETION_REVIEW:
                return JsonResponse(error("PRACTICE_STATE_CONFLICT", "实践尚未进入完成核验"), status=409)
            if HrEnterprisePracticeEvaluation.objects.filter(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
            ).exists():
                return JsonResponse(error("PRACTICE_EVALUATION_IMMUTABLE", "最终评价已经形成，不能覆盖"), status=409)
            precheck = PracticeProcessService.completion_precheck(assignment)
            if precheck["status"] != "PASS":
                return JsonResponse(error("PRACTICE_COMPLETION_BLOCKED", "完成核验前置条件未全部通过"), status=409)
            completion_status = body.get("completionStatus", PracticeEvaluationStatus.PASS)
            if completion_status not in PracticeEvaluationStatus.values:
                raise ValueError("最终评价状态无效")
            verified_hours = int(body.get("verifiedHours", 0))
            verified_days = int(body.get("verifiedDays", 0))
            if verified_hours < 0 or verified_days < 0:
                raise ValueError("核验时长不能为负数")
            evaluation = HrEnterprisePracticeEvaluation(
                tenant_id=tenant_id,
                assignment_id=assignment.id,
                project_version_id=body["projectVersionId"],
                enterprise_evaluation_ref=str(body.get("enterpriseEvaluationRef") or "").strip(),
                school_evaluation_ref=str(body.get("schoolEvaluationRef") or "").strip(),
                completion_status=completion_status,
                verified_hours=verified_hours,
                verified_days=verified_days,
                rubric_result_json=body.get("rubricResultJson", {}),
                final_comment=str(body.get("finalComment") or "").strip(),
                decided_by=request.user.id if request.user.is_authenticated else None,
                decided_at=datetime.now(timezone.utc),
            )
            evaluation.full_clean()
            evaluation.save()

            assignment.actual_verified_hours = verified_hours
            assignment.actual_verified_days = verified_days
            assignment.assignment_status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            assignment.save(update_fields=[
                "actual_verified_hours", "actual_verified_days", "assignment_status", "completed_at", "updated_at",
            ])
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    except IntegrityError:
        return JsonResponse(error("PRACTICE_EVALUATION_CONFLICT", "最终评价已由其他操作生成"), status=409)

    return JsonResponse(success({"id": str(evaluation.id), "completionStatus": evaluation.completion_status}))


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.process.record")
def create_output(request):
    """POST /api/v1/hr/development/development-outputs"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    try:
        staff_id = int(body["staffMasterId"])
        output_type = body.get("outputType", OutputType.OTHER)
        if output_type not in OutputType.values:
            raise ValueError("成果类型无效")
        with transaction.atomic():
            if not HrStaffMaster.objects.select_for_update().filter(
                tenant_id=tenant_id,
                legacy_employee_id=staff_id,
            ).exists():
                return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "教师不存在"), status=404)
            output = HrDevelopmentOutput(
                tenant_id=tenant_id,
                staff_master_id=staff_id,
                source_activity_type=str(body.get("sourceActivityType") or "").strip(),
                source_case_id=int(body.get("sourceCaseId") or 0),
                output_type=output_type,
                title=str(body["title"]).strip(),
                description=str(body.get("description") or "").strip(),
                evidence_refs=body.get("evidenceRefs", []),
                external_authority_ref=str(body.get("externalAuthorityRef") or "").strip(),
                verification_status=OutputVerificationStatus.SELF_REPORTED,
                created_by=request.user if request.user.is_authenticated else None,
                updated_by=request.user if request.user.is_authenticated else None,
            )
            output.full_clean()
            output.save()
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _invalid(exc)
    return JsonResponse(success({"id": str(output.id), "status": output.verification_status}), status=201)


@require_http_methods(["POST"])
@require_hr10_permission("hr.development.output.verify")
def verify_output(request, output_id):
    """POST /api/v1/hr/development/development-outputs/{id}/verify"""
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return JsonResponse(error(DevelopmentErrorCode.TENANT_CONTEXT_REQUIRED, "缺少租户上下文"), status=403)
    body = _body_object(request)
    if body is None:
        return JsonResponse(error("INVALID_JSON", "请求体不是有效 JSON"), status=400)
    target_status = body.get("verificationStatus", OutputVerificationStatus.VERIFIED)
    if target_status not in {
        OutputVerificationStatus.VERIFIED,
        OutputVerificationStatus.REJECTED,
        OutputVerificationStatus.SOURCE_UNAVAILABLE,
    }:
        return JsonResponse(error("INVALID_REQUEST", "成果核验状态无效"), status=400)

    with transaction.atomic():
        output = HrDevelopmentOutput.objects.select_for_update().filter(
            id=output_id,
            tenant_id=tenant_id,
        ).first()
        if not output:
            return JsonResponse(error(DevelopmentErrorCode.NOT_FOUND, "成果不存在"), status=404)
        if output.verification_status in {
            OutputVerificationStatus.VERIFIED,
            OutputVerificationStatus.SUPERSEDED,
        }:
            return JsonResponse(error("OUTPUT_VERIFICATION_IMMUTABLE", "成果核验结果已冻结"), status=409)

        output.verification_status = target_status
        output.verified_by = request.user.id if request.user.is_authenticated else None
        output.verified_at = datetime.now(timezone.utc)
        output.external_authority_ref = str(
            body.get("externalAuthorityRef", output.external_authority_ref) or ""
        ).strip()
        output.save(update_fields=[
            "verification_status", "verified_by", "verified_at", "external_authority_ref", "updated_at",
        ])

    return JsonResponse(success({"id": str(output.id), "status": output.verification_status}))
