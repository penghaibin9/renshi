"""HR12 Assessment — 基础 API 视图（生产级）。"""

from __future__ import annotations

import json
from datetime import datetime

from django.db.models import Count
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from hr_assessment.api.response import api_error, api_success
from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.models.case import (
    HrAnnualAssessmentCase,
    HrAssessmentCase,
    HrEthicsAssessmentCase,
    HrSubjectSnapshot,
    HrTermAssessmentCase,
)
from hr_assessment.models.goal import HrAssessmentGoal, HrGoalVersion
from hr_assessment.models.provider_snapshot import HrProviderSnapshotSet
from hr_assessment.models.evidence import HrReviewerAssignment
from hr_assessment.models.result import (
    HrAssessmentArchivePackage,
    HrAssessmentDocumentAccessAudit,
    HrAssessmentDecisionSession,
    HrCalibrationSession,
    HrFinalAssessmentResult,
    HrResultNotice,
    HrResultRevision,
)
from hr_assessment.models.cycle import HrAssessmentCycle, HrCycleSnapshot
from hr_assessment.models.policy import (
    HrAssessmentPolicyVersion,
    HrAssessmentWorkflowVersion,
    HrExcellentQuotaPolicy,
    HrIndicatorSetVersion,
    HrRatingScaleVersion,
    HrResultRuleVersion,
)
from hr_assessment.models.base import calculate_version_content_hash
from hr_assessment.service.annual import AnnualCaseService
from hr_assessment.service.population import CycleLifecycleService
from hr_assessment.selectors.cycle_utils import OrgAsOfResolver
from hr_staff.models import HrStaffMaster
from hr_assessment.permissions import require_assessment_permission
from hr_assessment.service.evidence import (
    EvidenceSnapshotError,
    ProviderCollectionOrchestrator,
    ProviderEvidenceSnapshotService,
)
from hr_assessment.services.finalization_service import (
    AssessmentFinalizationError,
    AssessmentFinalizationService,
    FinalResultInput,
)
from hr_assessment.services.result_correction_service import (
    AssessmentResultCorrectionError,
    AssessmentResultCorrectionService,
    ResultCorrectionInput,
    canonical_result_snapshot,
)
from hr_assessment.services.result_lifecycle_service import (
    AssessmentResultLifecycleError,
    AssessmentResultLifecycleService,
)
from hr_assessment.services.review_service import (
    AssessmentDecisionService,
    AssessmentReviewError,
    AssessmentReviewService,
    EvaluationInput,
    ReviewerAssignmentInput,
)
from hr_assessment.services.document_service import (
    AssessmentDocumentError,
    resolve_decision_minutes,
    store_decision_minutes,
)
from hr_assessment.services.objection_service import (
    AssessmentObjectionError,
    AssessmentObjectionService,
)

ANNUAL_GRADE_LABELS = {
    "EXCELLENT": "优秀",
    "QUALIFIED": "合格",
    "BASIC_QUALIFIED": "基本合格",
    "UNQUALIFIED": "不合格",
}

WORKBENCH_SECTIONS = {"goals", "term", "ethics", "review", "archive"}
GOAL_SOURCE_LABELS = {
    "POSITION_DUTY": "岗位职责",
    "ORG_GOAL": "组织目标",
    "INDIVIDUAL": "个人目标",
    "SELF_REPORT": "本人申报",
}
ASSESSMENT_TYPE_LABELS = {
    "ANNUAL": "年度考核",
    "TERM": "聘期考核",
    "ETHICS": "师德考核",
    "SPECIAL": "专项考核",
}


def _body(request: HttpRequest) -> dict | None:
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _aware_datetime(value) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed


@require_assessment_permission("hr.assessment.cycle.admin")
@require_http_methods(["GET"])
def setup_options(request: HttpRequest) -> JsonResponse:
    tenant = request.tenant_id
    policies = HrAssessmentPolicyVersion.objects.filter(
        tenant_id=tenant, status="PUBLISHED"
    ).select_related("policy_pack").order_by("-effective_from", "-version_no")
    cycles = HrAssessmentCycle.objects.filter(
        tenant_id=tenant, assessment_type="ANNUAL",
        lifecycle_status__in=["PUBLISHED", "ACTIVE"],
    ).order_by("-start_at")
    staff = HrStaffMaster.objects.filter(tenant_id=tenant).select_related("person_id").order_by("staff_no")[:1000]
    return JsonResponse(api_success(data={
        "policies": [{"value": str(item.id), "label": f"{item.policy_pack.name} · v{item.version_no}"} for item in policies],
        "cycles": [{"value": str(item.id), "label": f"{item.name} · {item.cycle_no}"} for item in cycles],
        "staff": [{"value": str(item.id), "label": f"{item.person_id.legal_name} · {item.staff_no}"} for item in staff],
    }))


@require_assessment_permission("hr.assessment.cycle.admin")
@require_http_methods(["POST"])
def create_cycle(request: HttpRequest) -> JsonResponse:
    tenant = request.tenant_id
    body = _body(request)
    if body is None:
        return JsonResponse(api_error("INVALID_REQUEST", "请求正文不是有效 JSON", http_status=400), status=400)
    cycle_no = str(body.get("cycleNo") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    try:
        start_at = _aware_datetime(body.get("startAt"))
        end_at = _aware_datetime(body.get("endAt"))
        policy = HrAssessmentPolicyVersion.objects.select_related("policy_pack").get(
            id=body.get("policyVersionId"), tenant_id=tenant, status="PUBLISHED"
        )
        business_year = int(body.get("businessYear") or start_at.year)
    except (TypeError, ValueError, HrAssessmentPolicyVersion.DoesNotExist):
        return JsonResponse(api_error("ASSESSMENT_CYCLE_INPUT_INVALID", "请选择已发布制度并填写有效周期信息", http_status=400), status=400)
    if not cycle_no or not name or end_at <= start_at:
        return JsonResponse(api_error("ASSESSMENT_CYCLE_INPUT_INVALID", "周期编号、名称或起止时间无效", http_status=400), status=400)
    try:
        with transaction.atomic():
            policy = HrAssessmentPolicyVersion.objects.select_for_update().get(
                id=policy.id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            scale = HrRatingScaleVersion.objects.select_for_update().get(
                id=policy.rating_scale_version_id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            indicator_set = HrIndicatorSetVersion.objects.select_for_update().get(
                id=policy.indicator_set_version_id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            workflow = HrAssessmentWorkflowVersion.objects.select_for_update().get(
                id=policy.workflow_version_id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            result_rule = HrResultRuleVersion.objects.select_for_update().get(
                id=policy.result_rule_version_id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            quota_policy = HrExcellentQuotaPolicy.objects.select_for_update().get(
                id=policy.excellent_quota_policy_id,
                tenant_id=tenant,
                status="PUBLISHED",
            )
            for authority in (
                policy,
                scale,
                indicator_set,
                workflow,
                result_rule,
                quota_policy,
            ):
                if authority.content_hash != calculate_version_content_hash(authority):
                    raise ValidationError(
                        f"ASSESSMENT_PUBLISHED_AUTHORITY_HASH_INVALID:{authority._meta.model_name}"
                    )
            cycle = HrAssessmentCycle.objects.create(
                tenant_id=tenant, cycle_no=cycle_no, assessment_type="ANNUAL", name=name,
                business_year=business_year, start_at=start_at, end_at=end_at,
                policy_version_id=policy.id,
            )
            lifecycle = CycleLifecycleService()
            for status in ("VALIDATING", "READY_TO_PUBLISH", "PUBLISHED"):
                lifecycle.transition(cycle, status)
            HrCycleSnapshot.objects.create(
                tenant_id=tenant, cycle=cycle,
                frozen_policy_json={
                    "id": str(policy.id),
                    "versionNo": policy.version_no,
                    "contentHash": policy.content_hash,
                    "resultRule": {
                        "id": str(result_rule.id),
                        "contentHash": result_rule.content_hash,
                        "scoreToGradeMapping": result_rule.score_to_grade_mapping,
                    },
                    "excellentQuota": {
                        "id": str(quota_policy.id),
                        "contentHash": quota_policy.content_hash,
                        "maxExcellentRatio": str(quota_policy.max_excellent_ratio),
                        "roundingRule": quota_policy.rounding_rule,
                        "minEligibleForQuota": quota_policy.min_eligible_for_quota,
                        "overQuotaAction": quota_policy.over_quota_action,
                    },
                },
                frozen_org_scope_json={"scope": "SCHOOL"},
                frozen_population_query_definition={"status": "ACTIVE"},
                frozen_rating_scale_json={
                    "id": str(scale.id),
                    "contentHash": scale.content_hash,
                    "scaleType": scale.scale_type,
                    "minValue": str(scale.min_value),
                    "maxValue": str(scale.max_value),
                    "levels": scale.levels,
                    "roundingRule": scale.rounding_rule,
                },
                frozen_indicator_set_json={
                    "id": str(indicator_set.id),
                    "contentHash": indicator_set.content_hash,
                    "totalWeight": str(indicator_set.total_weight),
                },
                frozen_workflow_json={
                    "id": str(workflow.id),
                    "contentHash": workflow.content_hash,
                    "name": workflow.name,
                },
                frozen_reviewer_rules_json={
                    "scoreAggregation": "AVERAGE",
                    "scoreField": "overallScore",
                },
                frozen_deadlines_json={"startAt": start_at.isoformat(), "endAt": end_at.isoformat()},
            )
    except (
        IntegrityError,
        ValidationError,
        HrAssessmentPolicyVersion.DoesNotExist,
        HrRatingScaleVersion.DoesNotExist,
        HrIndicatorSetVersion.DoesNotExist,
        HrAssessmentWorkflowVersion.DoesNotExist,
        HrResultRuleVersion.DoesNotExist,
        HrExcellentQuotaPolicy.DoesNotExist,
    ) as exc:
        return JsonResponse(api_error("ASSESSMENT_CYCLE_CONFLICT", str(exc), http_status=409), status=409)
    return JsonResponse(api_success(data={"id": str(cycle.id), "status": cycle.lifecycle_status}), status=201)


@require_assessment_permission("hr.assessment.cycle.admin")
@require_http_methods(["POST"])
def create_annual_case(request: HttpRequest) -> JsonResponse:
    tenant = request.tenant_id
    body = _body(request)
    if body is None:
        return JsonResponse(api_error("INVALID_REQUEST", "请求正文不是有效 JSON", http_status=400), status=400)
    cycle = HrAssessmentCycle.objects.filter(
        id=body.get("cycleId"), tenant_id=tenant, assessment_type="ANNUAL",
        lifecycle_status__in=["PUBLISHED", "ACTIVE"],
    ).first()
    staff = HrStaffMaster.objects.select_related("person_id").filter(id=body.get("staffId"), tenant_id=tenant).first()
    if cycle is None or staff is None:
        return JsonResponse(api_error("ASSESSMENT_CASE_INPUT_INVALID", "请选择当前学校有效周期和人员", http_status=400), status=400)
    try:
        with transaction.atomic():
            case = AnnualCaseService().create_case(
                tenant_id=tenant, cycle=cycle, staff_id=staff.id,
                business_year=cycle.business_year or cycle.start_at.year,
                policy_version_id=cycle.policy_version_id,
            )
            subject_as_of = OrgAsOfResolver().resolve(
                tenant,
                staff.id,
                cycle.start_at.date(),
            )
            subject = HrSubjectSnapshot.objects.create(
                tenant_id=tenant, case_id=case.id, staff_id=staff.id,
                display_name=staff.person_id.legal_name, staff_code=staff.staff_no,
                worker_category=staff.staff_category_code,
                org_id=subject_as_of.org_id,
                org_name=subject_as_of.org_name,
                position_id=subject_as_of.position_id,
                position_name=subject_as_of.position_name,
                job_category=subject_as_of.job_category,
                teacher_type=subject_as_of.teacher_type,
                reviewer_line_json={
                    "asOf": subject_as_of.as_of_date,
                    "source": "HR03_PRIMARY_ASSIGNMENT_HR02_AS_OF",
                    "directManagerId": (
                        str(subject_as_of.direct_manager_id)
                        if subject_as_of.direct_manager_id
                        else None
                    ),
                },
                snapshot_at=timezone.now(),
            )
            from hr_assessment.models.cycle import HrAssessmentPopulationSnapshot

            HrAssessmentPopulationSnapshot.objects.create(
                tenant_id=tenant,
                cycle=cycle,
                staff_id=staff.id,
                employment_relationship_id=subject_as_of.employment_relationship_id,
                primary_assignment_id=subject_as_of.primary_assignment_id,
                org_id=subject_as_of.org_id,
                position_id=subject_as_of.position_id,
                worker_category=staff.staff_category_code,
                classification_profile_json={
                    "source": "HR03_PRIMARY_ASSIGNMENT_HR02_AS_OF",
                    "asOf": subject_as_of.as_of_date,
                },
                included=True,
                excluded=False,
                snapshot_at=timezone.now(),
                policy_version_id=cycle.policy_version_id,
                eligibility_reason_codes=["ACTIVE_STAFF_SELECTED_BY_HR"],
            )
            if subject_as_of.direct_manager_id:
                HrReviewerAssignment.objects.create(
                    tenant_id=tenant,
                    case_id=case.id,
                    reviewer_role="DIRECT_MANAGER",
                    reviewer_staff_id=subject_as_of.direct_manager_id,
                    scope="ASSIGNED_CASES",
                    status="PENDING",
                )
            case.subject_snapshot = subject
            case.status = "PROPOSED"
            case.save(update_fields=["subject_snapshot", "status"])
            if cycle.lifecycle_status == "PUBLISHED":
                CycleLifecycleService().transition(cycle, "ACTIVE")
    except (IntegrityError, ValidationError, ValueError) as exc:
        return JsonResponse(api_error("ASSESSMENT_CASE_CONFLICT", str(exc), http_status=409), status=409)
    return JsonResponse(api_success(data={"id": str(case.id), "status": case.status}), status=201)


def _display_date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _display_datetime(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _subject_label(subject: HrSubjectSnapshot | None) -> str:
    if subject and subject.display_name:
        return subject.display_name
    return "人员档案暂不可用"


@require_assessment_permission("hr.assessment.analytics_view")
@require_http_methods(["GET"])
def workbench_rows(request: HttpRequest, section: str) -> JsonResponse:
    """Return bounded, tenant-scoped Authority facts for the five read workspaces."""
    if section not in WORKBENCH_SECTIONS:
        return JsonResponse(
            api_error("ASSESSMENT_WORKBENCH_UNKNOWN", "考核工作区不存在", http_status=404),
            status=404,
        )
    tenant = request.tenant_id
    rows: list[dict] = []

    if section == "goals":
        goals = list(
            HrAssessmentGoal.objects.filter(tenant_id=tenant)
            .select_related("goal_plan")
            .annotate(assignment_count=Count("assignments"))
            .order_by("-updated_at")[:100]
        )
        version_ids = [item.current_version_id for item in goals if item.current_version_id]
        versions = {
            item.id: item
            for item in HrGoalVersion.objects.filter(id__in=version_ids, goal__tenant_id=tenant)
        }
        for goal in goals:
            version = versions.get(goal.current_version_id)
            rows.append({
                "name": version.title if version else goal.goal_code,
                "sub": goal.goal_plan.name if goal.goal_plan else "未归入目标计划",
                "meta": f"{goal.assignment_count} 人承担 · {GOAL_SOURCE_LABELS.get(goal.source_type, '其它正式来源')}",
                "status": goal.status,
            })

    elif section == "term":
        cases = (
            HrTermAssessmentCase.objects.filter(tenant_id=tenant, assessment_type="TERM")
            .select_related("cycle", "subject_snapshot")
            .order_by("-term_end", "-created_at")[:100]
        )
        for case in cases:
            rows.append({
                "name": _subject_label(case.subject_snapshot),
                "sub": case.cycle.name if case.cycle else "聘期考核",
                "meta": f"{_display_date(case.term_start)} 至 {_display_date(case.term_end)}",
                "status": case.status,
            })

    elif section == "ethics":
        cases = (
            HrEthicsAssessmentCase.objects.filter(tenant_id=tenant, assessment_type="ETHICS")
            .select_related("cycle", "subject_snapshot")
            .order_by("-updated_at")[:100]
        )
        for case in cases:
            reason = "已记录独立判定原因" if case.gate_reason_code else "独立师德事实待核对"
            rows.append({
                "name": _subject_label(case.subject_snapshot),
                "sub": case.cycle.name if case.cycle else "师德专项考核",
                "meta": reason,
                "status": case.gate_status or case.status,
            })

    elif section == "review":
        decisions = (
            HrAssessmentDecisionSession.objects.filter(tenant_id=tenant)
            .order_by("-meeting_at", "-created_at")[:50]
        )
        calibrations = (
            HrCalibrationSession.objects.filter(tenant_id=tenant)
            .annotate(revision_count=Count("revisions"))
            .order_by("-opened_at", "-created_at")[:50]
        )
        for item in decisions:
            rows.append({
                "name": "正式审定会议",
                "sub": f"议程包含 {len(item.case_refs_json or [])} 个考核对象",
                "meta": _display_datetime(item.meeting_at) or "会议时间待定",
                "status": item.status,
            })
        for item in calibrations:
            rows.append({
                "name": "结果校准会",
                "sub": f"已记录 {item.revision_count} 项校准修订",
                "meta": _display_datetime(item.opened_at) or "尚未开始",
                "status": item.session_status,
            })

    else:
        results = list(
            HrFinalAssessmentResult.objects.filter(tenant_id=tenant)
            .annotate(
                archive_count=Count("archives", distinct=True),
                objection_count=Count("objections", distinct=True),
            )
            .order_by("-finalized_at", "-created_at")[:100]
        )
        case_ids = [item.case_id for item in results]
        subjects = {
            item.case_id: item
            for item in HrSubjectSnapshot.objects.filter(tenant_id=tenant, case_id__in=case_ids)
        }
        archive_status = {}
        for item in HrAssessmentArchivePackage.objects.filter(
            tenant_id=tenant,
            result_id__in=[item.id for item in results],
        ).order_by("result_id", "-created_at"):
            archive_status.setdefault(item.result_id, item.archive_status)
        for result in results:
            display_grade = result.display_grade_snapshot_json or {}
            grade = display_grade.get("zh-CN") or ANNUAL_GRADE_LABELS.get(result.grade_code) or result.grade_code
            rows.append({
                "name": _subject_label(subjects.get(result.case_id)),
                "sub": f"{ASSESSMENT_TYPE_LABELS.get(result.assessment_type, '考核结果')} · {grade or '正式结果'} · 版本 {result.result_version_no}",
                "meta": f"归档 {result.archive_count} · 异议 {result.objection_count}",
                "status": archive_status.get(result.id) or result.status,
            })

    return JsonResponse(api_success(data={"section": section, "rows": rows, "count": len(rows)}))


def ping(request: HttpRequest) -> JsonResponse:
    return JsonResponse(api_success(data={"status": "ok", "module": "hr_assessment", "stage": "production"}))


def eligibility_probe(request: HttpRequest) -> JsonResponse:
    tenant = resolve_tenant_from_assignment(request)
    if tenant is None:
        return JsonResponse(api_error("TENANT_CONTEXT_REQUIRED", "请选择当前学校", http_status=403), status=403)
    return JsonResponse(api_success(data={
        "tenantId": tenant,
        "scope": "CAPABILITY",
        "providerStatus": ProviderCollectionOrchestrator().capability_status(),
        "evidenceReadiness": "CASE_SCOPED_ONLY",
    }))


def _snapshot_payload(snapshot: HrProviderSnapshotSet) -> dict:
    return {
        "id": str(snapshot.id),
        "caseId": str(snapshot.case_id),
        "status": snapshot.status,
        "asOf": snapshot.as_of.isoformat(),
        "authority": snapshot.authority_json or {},
        "requiredProviders": snapshot.required_providers_json or [],
        "providerStatus": snapshot.provider_status_json or {},
        "capturedAt": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "requestId": snapshot.request_id or "",
    }


def _result_payload(result: HrFinalAssessmentResult) -> dict:
    canonical = canonical_result_snapshot(result)
    revision_manager = getattr(result, "revisions", None)
    latest_revision = (
        revision_manager.order_by("-new_version", "-effective_at", "-id").first()
        if revision_manager is not None
        else None
    )
    return {
        "id": str(result.id),
        "caseId": str(result.case_id),
        "status": canonical.get("status", result.status),
        "gradeCode": canonical.get("gradeCode", result.grade_code),
        "displayGrade": canonical.get(
            "displayGrade", result.display_grade_snapshot_json or {}
        ),
        "calculatedScore": canonical.get(
            "calculatedScore",
            str(result.calculated_score) if result.calculated_score is not None else None,
        ),
        "decisionReason": canonical.get("decisionReason", result.decision_reason or ""),
        "decisionSessionId": str(result.decision_session_id) if result.decision_session_id else None,
        "finalizedAt": result.finalized_at.isoformat() if result.finalized_at else None,
        "finalizedBy": str(result.finalized_by) if result.finalized_by else None,
        "resultVersionNo": canonical.get("version", result.result_version_no),
        "contentHash": (
            latest_revision.content_hash if latest_revision else result.content_hash
        ),
        "sourceResultContentHash": result.content_hash,
        "calculationHash": getattr(result, "calculation_hash", ""),
        "revisionId": str(latest_revision.id) if latest_revision else None,
        "sealedAt": (
            latest_revision.sealed_at.isoformat()
            if latest_revision and latest_revision.sealed_at
            else result.sealed_at.isoformat()
            if getattr(result, "sealed_at", None)
            else None
        ),
    }


def _revision_payload(revision: HrResultRevision) -> dict:
    return {
        "id": str(revision.id),
        "resultId": str(revision.result_id),
        "correctionNo": revision.correction_no,
        "previousVersion": revision.previous_version,
        "newVersion": revision.new_version,
        "revisionType": revision.revision_type,
        "reason": revision.reason,
        "authorityStaffId": (
            str(revision.authority_staff_id) if revision.authority_staff_id else None
        ),
        "before": revision.before_snapshot_json or {},
        "after": revision.after_snapshot_json or {},
        "effectiveAt": (
            revision.effective_at.isoformat() if revision.effective_at else None
        ),
        "contentHash": revision.content_hash,
        "sealedAt": revision.sealed_at.isoformat() if revision.sealed_at else None,
    }


def _notice_payload(notice) -> dict:
    return {
        "id": str(notice.id),
        "resultId": str(notice.result_id),
        "noticeNo": notice.notice_no,
        "resultVersion": notice.result_version,
        "generatedDocumentId": (
            str(notice.generated_document_id) if notice.generated_document_id else None
        ),
        "deliveryChannel": notice.delivery_channel,
        "deliveryStatus": notice.delivery_status,
        "deliveryReceiptRef": notice.delivery_receipt_ref,
        "deliveredAt": notice.delivered_at.isoformat() if notice.delivered_at else None,
    }


def _acknowledgement_payload(acknowledgement) -> dict:
    return {
        "id": str(acknowledgement.id),
        "resultId": str(acknowledgement.result_id),
        "resultVersion": acknowledgement.result_version,
        "acknowledgementStatus": acknowledgement.acknowledgement_status,
        "employeeOpinion": acknowledgement.employee_opinion,
        "receivedAt": (
            acknowledgement.received_at.isoformat()
            if acknowledgement.received_at
            else None
        ),
        "confirmedAt": (
            acknowledgement.confirmed_at.isoformat()
            if acknowledgement.confirmed_at
            else None
        ),
    }


def _archive_payload(archive) -> dict:
    return {
        "id": str(archive.id),
        "resultId": str(archive.result_id),
        "archivePackageId": archive.archive_package_id,
        "resultVersion": archive.result_version,
        "documentRefs": archive.document_refs_json or [],
        "archiveStatus": archive.archive_status,
        "contentHash": archive.content_hash,
        "archiveProviderRef": archive.archive_provider_ref,
        "archivedAt": archive.archived_at.isoformat() if archive.archived_at else None,
        "sealedAt": archive.sealed_at.isoformat() if archive.sealed_at else None,
    }


def _objection_payload(objection, *, include_reason: bool = False) -> dict:
    payload = {
        "id": str(objection.id),
        "resultId": str(objection.result_id),
        "resultVersion": objection.result_version,
        "status": objection.status,
        "decisionCode": objection.decision_code,
        "conclusion": objection.conclusion,
        "resolutionRevisionId": (
            str(objection.resolution_revision_id)
            if objection.resolution_revision_id else None
        ),
        "submittedAt": objection.submitted_at.isoformat(),
        "resolvedAt": objection.resolved_at.isoformat() if objection.resolved_at else None,
    }
    if include_reason:
        payload["reason"] = objection.reason
        payload["evidenceRefs"] = objection.evidence_json or []
    return payload


def _reviewer_assignment_payload(assignment) -> dict:
    return {
        "id": str(assignment.id),
        "caseId": str(assignment.case_id),
        "reviewerStaffId": str(assignment.reviewer_staff_id),
        "reviewerRole": assignment.reviewer_role,
        "status": assignment.status,
        "dueAt": assignment.due_at.isoformat() if assignment.due_at else None,
        "conflictStatus": assignment.conflict_status,
    }


def _reviewer_task_payload(assignment, staff_names: dict[str, str]) -> dict:
    payload = _reviewer_assignment_payload(assignment)
    case = getattr(assignment, "assessment_case", None)
    subject = getattr(case, "subject_snapshot", None) if case else None
    latest = assignment.evaluations.order_by("-revision_no", "-submitted_at").first()
    payload.update({
        "staffName": subject.display_name if subject else "人员档案暂不可用",
        "cycleName": case.cycle.name if case and case.cycle else "",
        "caseStatus": case.status if case else "",
        "reviewerName": staff_names.get(str(assignment.reviewer_staff_id), ""),
        "evaluation": _evaluation_payload(latest) if latest else None,
    })
    return payload


def _evaluation_payload(evaluation) -> dict:
    return {
        "id": str(evaluation.id),
        "assignmentId": str(evaluation.assignment_id),
        "rating": evaluation.rating_json or {},
        "comment": evaluation.comment,
        "indicatorEvaluations": evaluation.indicator_evaluations_json or [],
        "revisionNo": evaluation.revision_no,
        "submittedAt": evaluation.submitted_at.isoformat() if evaluation.submitted_at else None,
    }


def _decision_payload(session) -> dict:
    return {
        "id": str(session.id),
        "cycleId": str(session.cycle_id),
        "bodyOrgId": session.body_org_id,
        "meetingAt": session.meeting_at.isoformat() if session.meeting_at else None,
        "quorumPolicy": session.quorum_policy_json or {},
        "participants": session.participants_json or [],
        "caseIds": session.case_refs_json or [],
        "status": session.status,
        "minutesDocumentRef": (
            str(session.minutes_document_ref) if session.minutes_document_ref else None
        ),
    }


def _staff_option_rows(tenant_id: int) -> list[dict]:
    staff = (
        HrStaffMaster.objects.filter(tenant_id=tenant_id)
        .select_related("person_id")
        .order_by("person_id__legal_name", "staff_no")[:2000]
    )
    return [
        {
            "value": str(item.id),
            "label": f"{item.person_id.legal_name} · {item.staff_no}",
        }
        for item in staff
    ]


def _annual_decision_map(cases: list[HrAnnualAssessmentCase], tenant_id: int) -> dict[str, str]:
    case_ids = {str(item.id) for item in cases}
    cycle_ids = {item.cycle_id for item in cases if item.cycle_id}
    if not case_ids or not cycle_ids:
        return {}
    mapping: dict[str, str] = {}
    sessions = HrAssessmentDecisionSession.objects.filter(
        tenant_id=tenant_id,
        cycle_id__in=cycle_ids,
        status__in=AssessmentFinalizationService.DECISION_COMPLETE,
    ).order_by("-meeting_at", "-created_at")
    for session in sessions:
        for case_ref in session.case_refs_json or []:
            key = str(case_ref)
            if key in case_ids and key not in mapping:
                mapping[key] = str(session.id)
    return mapping


@require_assessment_permission("hr.assessment.hr_reviewer")
@require_http_methods(["GET"])
def annual_case_list(request: HttpRequest) -> JsonResponse:
    tenant = request.tenant_id
    cases = list(
        HrAnnualAssessmentCase.objects.filter(tenant_id=tenant, assessment_type="ANNUAL")
        .select_related("cycle", "subject_snapshot")
        .order_by("-business_year", "-created_at")[:200]
    )
    case_ids = [item.id for item in cases]
    result_map = {
        str(item.case_id): item
        for item in HrFinalAssessmentResult.objects.filter(tenant_id=tenant, case_id__in=case_ids)
    }
    snapshot_ids = [item.provider_snapshot_set_id for item in cases if item.provider_snapshot_set_id]
    snapshot_map = {
        str(item.id): item
        for item in HrProviderSnapshotSet.objects.filter(tenant_id=tenant, id__in=snapshot_ids)
    }
    decision_map = _annual_decision_map(cases, tenant)
    rows = []
    for case in cases:
        snapshot = snapshot_map.get(str(case.provider_snapshot_set_id))
        result = result_map.get(str(case.id))
        subject = case.subject_snapshot
        rows.append({
            "id": str(case.id),
            "staffId": str(case.staff_id),
            "staffName": subject.display_name if subject else "",
            "cycleId": str(case.cycle_id) if case.cycle_id else None,
            "cycleName": case.cycle.name if case.cycle else "",
            "businessYear": case.business_year,
            "academicYear": case.academic_year or "",
            "status": case.status,
            "providerSnapshotId": str(case.provider_snapshot_set_id) if case.provider_snapshot_set_id else None,
            "providerSnapshotStatus": snapshot.status if snapshot else None,
            "providerSnapshotReady": bool(snapshot and snapshot.status == "READY"),
            "decisionSessionId": decision_map.get(str(case.id)),
            "formalResult": _result_payload(result) if result else None,
        })
    return JsonResponse(api_success(data=rows))


@require_assessment_permission("hr.assessment.hr_reviewer")
@require_http_methods(["GET", "POST"])
def provider_snapshot(request: HttpRequest, case_id) -> JsonResponse:
    tenant = getattr(request, "tenant_id", None)
    request_id = request.headers.get("X-Request-ID", "")
    case = HrAssessmentCase.objects.filter(id=case_id, tenant_id=tenant).first()
    if case is None:
        return JsonResponse(api_error(
            "ASSESSMENT_CASE_NOT_FOUND",
            "考核 Case 不存在或不属于当前学校",
            request_id=request_id,
            http_status=404,
        ), status=404)
    if request.method == "GET":
        if not case.provider_snapshot_set_id:
            return JsonResponse(api_success(data={"caseId": str(case.id), "snapshot": None}, request_id=request_id))
        snapshot = HrProviderSnapshotSet.objects.filter(
            id=case.provider_snapshot_set_id,
            tenant_id=tenant,
            case_id=case.id,
        ).first()
        if snapshot is None:
            return JsonResponse(api_error(
                "ASSESSMENT_PROVIDER_SNAPSHOT_STATE_DRIFT",
                "Case 指向的 Provider 快照不存在",
                details={"snapshotSetId": str(case.provider_snapshot_set_id)},
                request_id=request_id,
                http_status=409,
            ), status=409)
        return JsonResponse(api_success(
            data={"caseId": str(case.id), "snapshot": _snapshot_payload(snapshot)},
            request_id=request_id,
        ))
    try:
        snapshot = ProviderEvidenceSnapshotService(tenant).capture_case_from_policy(
            case_id=case.id,
            request_id=request_id,
        )
    except EvidenceSnapshotError as exc:
        status = 404 if exc.code == "ASSESSMENT_CASE_NOT_FOUND" else 409
        return JsonResponse(api_error(exc.code, str(exc), request_id=request_id, http_status=status), status=status)
    return JsonResponse(api_success(
        data={"caseId": str(case.id), "snapshot": _snapshot_payload(snapshot)},
        request_id=request_id,
    ))


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def finalize_case(request: HttpRequest, case_id) -> JsonResponse:
    tenant = request.tenant_id
    request_id = request.headers.get("X-Request-ID", "")
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(api_error(
            "INVALID_REQUEST", "请求正文不是有效 JSON", request_id=request_id, http_status=400,
        ), status=400)
    forbidden_authority_fields = {
        "gradeCode",
        "displayGrade",
        "calculatedScore",
        "totalScore",
        "rank",
        "rankNo",
        "outcome",
        "scoreSnapshot",
        "snapshot",
    }.intersection(payload)
    if forbidden_authority_fields:
        return JsonResponse(api_error(
            "ASSESSMENT_CLIENT_AUTHORITY_FIELDS_FORBIDDEN",
            "最终分数、档次、名次、结论和权威快照只能由服务端计算",
            details={"fields": sorted(forbidden_authority_fields)},
            request_id=request_id,
            http_status=400,
        ), status=400)
    decision_session_id = str(payload.get("decisionSessionId") or "").strip()
    if not decision_session_id:
        return JsonResponse(api_error(
            "ASSESSMENT_DECISION_SESSION_REQUIRED",
            "正式审定前必须选择已完成的审定会话",
            request_id=request_id,
            http_status=400,
        ), status=400)
    try:
        result = AssessmentFinalizationService(
            tenant,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).finalize(
            case_id=case_id,
            payload=FinalResultInput(
                decision_reason=str(payload.get("decisionReason") or "年度考核工作台正式审定").strip(),
                decision_session_id=decision_session_id,
            ),
        )
    except AssessmentFinalizationError as exc:
        status = 404 if exc.code == "ASSESSMENT_CASE_NOT_FOUND" else 409
        return JsonResponse(api_error(
            exc.code,
            str(exc),
            details={"blockers": exc.blockers} if exc.blockers else None,
            request_id=request_id,
            http_status=status,
        ), status=status)
    return JsonResponse(api_success(
        data={"caseId": str(case_id), "result": _result_payload(result)},
        request_id=request_id,
    ))


@require_assessment_permission("hr.assessment.result.correct")
@require_http_methods(["GET", "POST"])
def result_corrections(request: HttpRequest, result_id) -> JsonResponse:
    """Read or append the immutable correction/revocation chain."""

    tenant = request.tenant_id
    request_id = request.headers.get("X-Request-ID", "")
    result = HrFinalAssessmentResult.objects.filter(
        id=result_id,
        tenant_id=tenant,
    ).first()
    if result is None:
        return JsonResponse(
            api_error(
                "ASSESSMENT_RESULT_NOT_FOUND",
                "正式考核结果不存在或不属于当前学校",
                request_id=request_id,
                http_status=404,
            ),
            status=404,
        )
    if request.method == "GET":
        revisions = result.revisions.order_by("new_version", "created_at")
        return JsonResponse(
            api_success(
                data={
                    "result": _result_payload(result),
                    "revisions": [_revision_payload(item) for item in revisions],
                },
                request_id=request_id,
            )
        )
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            api_error(
                "INVALID_REQUEST",
                "请求正文不是有效 JSON",
                request_id=request_id,
                http_status=400,
            ),
            status=400,
        )
    try:
        revision = AssessmentResultCorrectionService(
            tenant,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).append(
            result_id=result_id,
            payload=ResultCorrectionInput(
                correction_no=body.get("correctionNo"),
                expected_version=body.get("expectedVersion"),
                revision_type=body.get("revisionType"),
                reason=body.get("reason"),
                changes=body.get("changes", {}),
            ),
        )
    except AssessmentResultCorrectionError as exc:
        status = 404 if exc.code == "ASSESSMENT_RESULT_NOT_FOUND" else 409
        if exc.code.endswith("_INVALID") or exc.code.endswith("_REQUIRED") or exc.code.endswith("_FORBIDDEN"):
            status = 400
        return JsonResponse(
            api_error(
                exc.code,
                str(exc),
                request_id=request_id,
                http_status=status,
            ),
            status=status,
        )
    return JsonResponse(
        api_success(data={"revision": _revision_payload(revision)}, request_id=request_id),
        status=201,
    )


def _lifecycle_error_response(exc, request_id: str) -> JsonResponse:
    status = 404 if exc.code.endswith("_NOT_FOUND") else 409
    if (
        exc.code.endswith("_INVALID")
        or exc.code.endswith("_REQUIRED")
        or exc.code.endswith("_FORBIDDEN")
        or exc.code == "INVALID_REQUEST"
    ):
        status = 400
    if exc.code == "ASSESSMENT_ACK_SELF_SCOPE_REQUIRED":
        status = 403
    return JsonResponse(
        api_error(
            exc.code,
            str(exc),
            request_id=request_id,
            http_status=status,
        ),
        status=status,
    )


def _request_json(request: HttpRequest) -> dict:
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AssessmentResultLifecycleError(
            "INVALID_REQUEST", "请求正文不是有效 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise AssessmentResultLifecycleError(
            "INVALID_REQUEST", "请求正文必须是 JSON 对象"
        )
    return value


@require_assessment_permission(
    (
        "hr.assessment.final_decider",
        "hr.assessment.archive_manager",
        "hr.assessment.auditor",
        "hr.assessment.hr_reviewer",
        "hr.assessment.result.correct",
        "hr.assessment.employee_self",
    )
)
@require_http_methods(["GET"])
def result_lifecycle_list(request: HttpRequest) -> JsonResponse:
    broad_codes = (
        "hr.assessment.final_decider",
        "hr.assessment.archive_manager",
        "hr.assessment.auditor",
        "hr.assessment.hr_reviewer",
        "hr.assessment.result.correct",
    )
    broad = request.user.is_superuser or any(
        request.user.has_perm(code) for code in broad_codes
    )
    results = HrFinalAssessmentResult.objects.filter(tenant_id=request.tenant_id)
    if not broad:
        staff_id = getattr(request, "staff_id", None)
        if not staff_id:
            return JsonResponse(
                api_error(
                    "STAFF_ACCOUNT_LINK_REQUIRED",
                    "当前账号未关联教职工主档",
                    http_status=403,
                ),
                status=403,
            )
        own_cases = HrAssessmentCase.objects.filter(
            tenant_id=request.tenant_id,
            staff_id=staff_id,
        ).values_list("id", flat=True)
        results = results.filter(case_id__in=own_cases)
    results = list(results.order_by("-finalized_at", "-created_at")[:500])
    case_map = {
        str(item.id): item
        for item in HrAssessmentCase.objects.filter(
            tenant_id=request.tenant_id,
            id__in=[item.case_id for item in results],
        ).select_related("subject_snapshot", "cycle")
    }
    result_ids = [item.id for item in results]
    notices = {}
    for item in HrResultNotice.objects.filter(
        tenant_id=request.tenant_id,
        result_id__in=result_ids,
    ).order_by("result_id", "-result_version", "-created_at"):
        notices.setdefault((str(item.result_id), int(item.result_version)), item)
    acknowledgements = {}
    from hr_assessment.models.result import HrAcknowledgement

    for item in HrAcknowledgement.objects.filter(
        tenant_id=request.tenant_id,
        result_id__in=result_ids,
    ).order_by("result_id", "-result_version", "-created_at"):
        acknowledgements.setdefault((str(item.result_id), int(item.result_version)), item)
    archives = {}
    for item in HrAssessmentArchivePackage.objects.filter(
        tenant_id=request.tenant_id,
        result_id__in=result_ids,
    ).order_by("result_id", "-result_version", "-created_at"):
        archives.setdefault((str(item.result_id), int(item.result_version)), item)
    objections = {}
    from hr_assessment.models.result import HrAssessmentObjection

    for item in HrAssessmentObjection.objects.filter(
        tenant_id=request.tenant_id,
        result_id__in=result_ids,
    ).order_by("result_id", "-result_version", "-submitted_at"):
        objections.setdefault((str(item.result_id), int(item.result_version)), item)
    can_issue = request.user.is_superuser or request.user.has_perm(
        "hr.assessment.final_decider"
    )
    can_archive = request.user.is_superuser or request.user.has_perm(
        "hr.assessment.archive_manager"
    )
    rows = []
    for result in results:
        key = str(result.id)
        result_payload = _result_payload(result)
        current_version = int(result_payload.get("resultVersionNo") or 1)
        case = case_map.get(str(result.case_id))
        lifecycle_key = (key, current_version)
        notice = notices.get(lifecycle_key)
        acknowledgement = acknowledgements.get(lifecycle_key)
        archive = archives.get(lifecycle_key)
        objection = objections.get(lifecycle_key)
        own = bool(
            case
            and getattr(request, "staff_id", None)
            and str(case.staff_id) == str(request.staff_id)
        )
        rows.append({
            "result": result_payload,
            "staffName": _subject_label(case.subject_snapshot if case else None),
            "cycleName": case.cycle.name if case and case.cycle else "",
            "notice": _notice_payload(notice) if notice else None,
            "acknowledgement": (
                _acknowledgement_payload(acknowledgement)
                if acknowledgement else None
            ),
            "objection": (
                _objection_payload(objection, include_reason=(broad or own))
                if objection else None
            ),
            "archive": _archive_payload(archive) if archive else None,
            "actions": {
                "canIssueNotice": can_issue and notice is None,
                "canConfirmDelivery": can_issue and bool(
                    notice and notice.delivery_status == "PENDING"
                ),
                "canAcknowledge": own and bool(
                    notice and notice.delivery_status == "DELIVERED" and not acknowledgement
                ),
                "canSubmitObjection": own and bool(
                    notice and notice.delivery_status == "DELIVERED" and not objection
                ),
                "canDecideObjection": bool(
                    objection and objection.status != "CLOSED"
                    and (
                        request.user.is_superuser
                        or request.user.has_perm("hr.assessment.result.correct")
                    )
                ),
                "canArchive": can_archive and archive is None,
            },
        })
    return JsonResponse(api_success(data=rows))


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def issue_result_notice(request: HttpRequest, result_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        notice = AssessmentResultLifecycleService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).issue_notice(
            result_id=result_id,
            notice_no=body.get("noticeNo"),
            delivery_channel=body.get("deliveryChannel", "SYSTEM"),
            generated_document_id=body.get("generatedDocumentId"),
        )
    except (
        AssessmentResultLifecycleError,
        IntegrityError,
        ValidationError,
        ValueError,
    ) as exc:
        if not isinstance(exc, AssessmentResultLifecycleError):
            code = (
                "ASSESSMENT_NOTICE_IDEMPOTENCY_CONFLICT"
                if isinstance(exc, IntegrityError)
                else "ASSESSMENT_NOTICE_DOCUMENT_ID_INVALID"
            )
            exc = AssessmentResultLifecycleError(code, str(exc))
        return _lifecycle_error_response(exc, request_id)
    return JsonResponse(
        api_success(data={"notice": _notice_payload(notice)}, request_id=request_id),
        status=201,
    )


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def confirm_result_notice_delivery(request: HttpRequest, notice_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        notice = AssessmentResultLifecycleService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).confirm_delivery(
            notice_id=notice_id,
            delivery_receipt_ref=body.get("deliveryReceiptRef"),
        )
    except AssessmentResultLifecycleError as exc:
        return _lifecycle_error_response(exc, request_id)
    return JsonResponse(
        api_success(data={"notice": _notice_payload(notice)}, request_id=request_id)
    )


@require_assessment_permission("hr.assessment.employee_self")
@require_http_methods(["POST"])
def acknowledge_result(request: HttpRequest, result_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        acknowledgement = AssessmentResultLifecycleService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).acknowledge(
            result_id=result_id,
            acknowledgement_status=body.get("acknowledgementStatus"),
            employee_opinion=body.get("employeeOpinion", ""),
        )
    except AssessmentResultLifecycleError as exc:
        return _lifecycle_error_response(exc, request_id)
    return JsonResponse(
        api_success(
            data={"acknowledgement": _acknowledgement_payload(acknowledgement)},
            request_id=request_id,
        ),
        status=201,
    )


@require_assessment_permission(
    "hr.assessment.employee_self",
    staff_mapping_required=True,
)
@require_http_methods(["POST"])
def submit_result_objection(request: HttpRequest, result_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        evidence_refs = body.get("evidenceRefs", [])
        if not isinstance(evidence_refs, list):
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_EVIDENCE_INVALID",
                "evidenceRefs 必须是数组",
                status=400,
            )
        objection = AssessmentObjectionService(
            request.tenant_id,
            actor_staff_id=request.staff_id,
            correlation_id=request_id,
        ).submit(
            result_id=result_id,
            reason=body.get("reason"),
            evidence_refs=evidence_refs,
        )
    except AssessmentResultLifecycleError as exc:
        return _lifecycle_error_response(exc, request_id)
    except AssessmentObjectionError as exc:
        return JsonResponse(
            api_error(exc.code, exc.message, request_id=request_id, http_status=exc.status),
            status=exc.status,
        )
    return JsonResponse(
        api_success(
            data={"objection": _objection_payload(objection, include_reason=True)},
            request_id=request_id,
        ),
        status=201,
    )


@require_assessment_permission(
    "hr.assessment.result.correct",
    staff_mapping_required=True,
)
@require_http_methods(["POST"])
def decide_result_objection(request: HttpRequest, objection_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        changes = body.get("changes", {})
        if not isinstance(changes, dict):
            raise AssessmentObjectionError(
                "ASSESSMENT_RESULT_CHANGES_INVALID", "changes 必须是对象", status=400
            )
        objection = AssessmentObjectionService(
            request.tenant_id,
            actor_staff_id=request.staff_id,
            correlation_id=request_id,
        ).decide(
            objection_id=objection_id,
            decision_code=body.get("decisionCode"),
            conclusion=body.get("conclusion"),
            expected_version=body.get("expectedVersion"),
            changes=changes,
        )
    except AssessmentResultLifecycleError as exc:
        return _lifecycle_error_response(exc, request_id)
    except AssessmentObjectionError as exc:
        return JsonResponse(
            api_error(exc.code, exc.message, request_id=request_id, http_status=exc.status),
            status=exc.status,
        )
    return JsonResponse(api_success(
        data={"objection": _objection_payload(objection, include_reason=True)},
        request_id=request_id,
    ))


@require_assessment_permission("hr.assessment.archive_manager")
@require_http_methods(["POST"])
def archive_result(request: HttpRequest, result_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        document_refs = body.get("documentRefs", [])
        if not isinstance(document_refs, list):
            raise AssessmentResultLifecycleError(
                "ASSESSMENT_ARCHIVE_DOCUMENT_REF_INVALID",
                "documentRefs must be an array",
            )
        archive = AssessmentResultLifecycleService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).archive(result_id=result_id, document_refs=document_refs)
    except AssessmentResultLifecycleError as exc:
        return _lifecycle_error_response(exc, request_id)
    return JsonResponse(
        api_success(data={"archive": _archive_payload(archive)}, request_id=request_id),
        status=201,
    )


def _review_error_response(exc, request_id: str) -> JsonResponse:
    status = 404 if exc.code.endswith("_NOT_FOUND") else 409
    if (
        exc.code.endswith("_INVALID")
        or exc.code.endswith("_REQUIRED")
        or exc.code == "INVALID_REQUEST"
    ):
        status = 400
    if exc.code.endswith("_SELF_SCOPE_REQUIRED"):
        status = 403
    return JsonResponse(
        api_error(exc.code, str(exc), request_id=request_id, http_status=status),
        status=status,
    )


@require_assessment_permission("hr.assessment.hr_reviewer")
@require_http_methods(["GET"])
def review_administration_options(request: HttpRequest) -> JsonResponse:
    cases = (
        HrAnnualAssessmentCase.objects.filter(
            tenant_id=request.tenant_id,
            assessment_type="ANNUAL",
            status__in=AssessmentReviewService.CASE_STATES,
        )
        .select_related("cycle", "subject_snapshot")
        .order_by("-business_year", "subject_snapshot__display_name")[:1000]
    )
    return JsonResponse(api_success(data={
        "cases": [
            {
                "value": str(item.id),
                "label": (
                    f"{_subject_label(item.subject_snapshot)} · "
                    f"{item.cycle.name if item.cycle else '未命名周期'}"
                ),
            }
            for item in cases
        ],
        "staff": _staff_option_rows(request.tenant_id),
        "reviewerRoles": [
            {"value": "DIRECT_MANAGER", "label": "直接主管"},
            {"value": "DEPARTMENT_REVIEWER", "label": "系（部门）评议"},
            {"value": "COLLEGE_REVIEWER", "label": "学院评议"},
            {"value": "HR_REVIEWER", "label": "学校人事复核"},
            {"value": "PANEL_MEMBER", "label": "考核委员会成员"},
        ],
    }))


@require_assessment_permission(
    (
        "hr.assessment.manager_reviewer",
        "hr.assessment.college_reviewer",
        "hr.assessment.hr_reviewer",
        "hr.assessment.panel_member",
    ),
    staff_mapping_required=True,
)
@require_http_methods(["GET"])
def my_reviewer_assignments(request: HttpRequest) -> JsonResponse:
    assignments = list(
        HrReviewerAssignment.objects.filter(
            tenant_id=request.tenant_id,
            reviewer_staff_id=request.staff_id,
        ).prefetch_related("evaluations").order_by("status", "due_at", "assigned_at")[:500]
    )
    case_map = {
        str(item.id): item
        for item in HrAssessmentCase.objects.filter(
            tenant_id=request.tenant_id,
            id__in=[item.case_id for item in assignments],
        ).select_related("cycle", "subject_snapshot")
    }
    for assignment in assignments:
        assignment.assessment_case = case_map.get(str(assignment.case_id))
    staff_names = {
        item["value"]: item["label"]
        for item in _staff_option_rows(request.tenant_id)
        if item["value"] == str(request.staff_id)
    }
    return JsonResponse(api_success(data=[
        _reviewer_task_payload(item, staff_names) for item in assignments
    ]))


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["GET"])
def decision_options(request: HttpRequest) -> JsonResponse:
    finalized_case_ids = HrFinalAssessmentResult.objects.filter(
        tenant_id=request.tenant_id
    ).values_list("case_id", flat=True)
    cases = list(
        HrAnnualAssessmentCase.objects.filter(
            tenant_id=request.tenant_id,
            assessment_type="ANNUAL",
            status__in={"PROPOSED", "PUBLICITY"},
        ).exclude(id__in=finalized_case_ids)
        .select_related("cycle", "subject_snapshot")
        .order_by("-business_year", "subject_snapshot__display_name")[:1000]
    )
    cycles = {}
    for case in cases:
        if case.cycle:
            cycles[str(case.cycle_id)] = {
                "value": str(case.cycle_id),
                "label": f"{case.cycle.name} · {case.cycle.cycle_no}",
            }
    return JsonResponse(api_success(data={
        "cycles": list(cycles.values()),
        "cases": [
            {
                "value": str(item.id),
                "cycleId": str(item.cycle_id),
                "label": f"{_subject_label(item.subject_snapshot)} · {item.business_year or ''}",
            }
            for item in cases
        ],
        "staff": _staff_option_rows(request.tenant_id),
    }))


@require_assessment_permission("hr.assessment.hr_reviewer")
@require_http_methods(["POST"])
def assign_case_reviewer(request: HttpRequest, case_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        due_at = _aware_datetime(body.get("dueAt")) if body.get("dueAt") else None
        assignment = AssessmentReviewService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).assign_reviewer(
            case_id=case_id,
            payload=ReviewerAssignmentInput(
                reviewer_staff_id=body.get("reviewerStaffId"),
                reviewer_role=body.get("reviewerRole"),
                due_at=due_at,
            ),
        )
    except (AssessmentReviewError, ValueError, TypeError) as exc:
        if not isinstance(exc, AssessmentReviewError):
            exc = AssessmentReviewError("ASSESSMENT_REVIEWER_DUE_AT_INVALID", str(exc))
        return _review_error_response(exc, request_id)
    return JsonResponse(
        api_success(
            data={"assignment": _reviewer_assignment_payload(assignment)},
            request_id=request_id,
        ),
        status=201,
    )


@require_assessment_permission(
    (
        "hr.assessment.manager_reviewer",
        "hr.assessment.college_reviewer",
        "hr.assessment.hr_reviewer",
        "hr.assessment.panel_member",
    ),
    staff_mapping_required=True,
)
@require_http_methods(["POST"])
def submit_reviewer_evaluation(request: HttpRequest, assignment_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        evaluation = AssessmentReviewService(
            request.tenant_id,
            actor_staff_id=request.staff_id,
            correlation_id=request_id,
        ).submit_evaluation(
            assignment_id=assignment_id,
            payload=EvaluationInput(
                overall_score=body.get("overallScore"),
                comment=body.get("comment"),
                indicator_evaluations=body.get("indicatorEvaluations", []),
            ),
        )
    except AssessmentReviewError as exc:
        return _review_error_response(exc, request_id)
    return JsonResponse(
        api_success(
            data={"evaluation": _evaluation_payload(evaluation)},
            request_id=request_id,
        ),
        status=201,
    )


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def create_decision_session(request: HttpRequest, cycle_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        case_ids = body.get("caseIds", [])
        participants = body.get("participantStaffIds", [])
        if not isinstance(case_ids, list) or not isinstance(participants, list):
            raise AssessmentReviewError(
                "ASSESSMENT_DECISION_INPUT_INVALID",
                "caseIds and participantStaffIds must be arrays",
            )
        meeting_at = _aware_datetime(body.get("meetingAt"))
        session = AssessmentDecisionService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).create_session(
            cycle_id=cycle_id,
            case_ids=case_ids,
            participant_staff_ids=participants,
            required_count=body.get("requiredCount"),
            meeting_at=meeting_at,
            body_org_id=body.get("bodyOrgId"),
        )
    except (AssessmentReviewError, ValueError, TypeError) as exc:
        if not isinstance(exc, AssessmentReviewError):
            exc = AssessmentReviewError("ASSESSMENT_DECISION_INPUT_INVALID", str(exc))
        return _review_error_response(exc, request_id)
    return JsonResponse(
        api_success(data={"decisionSession": _decision_payload(session)}, request_id=request_id),
        status=201,
    )


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def complete_decision_session(request: HttpRequest, session_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        body = _request_json(request)
        session = AssessmentDecisionService(
            request.tenant_id,
            actor_staff_id=getattr(request, "staff_id", None),
            correlation_id=request_id,
        ).complete_session(
            session_id=session_id,
            minutes_document_ref=body.get("minutesDocumentRef"),
        )
    except (AssessmentReviewError, ValueError) as exc:
        if not isinstance(exc, AssessmentReviewError):
            exc = AssessmentReviewError("ASSESSMENT_DECISION_MINUTES_INVALID", str(exc))
        return _review_error_response(exc, request_id)
    return JsonResponse(
        api_success(data={"decisionSession": _decision_payload(session)}, request_id=request_id)
    )


@require_assessment_permission("hr.assessment.final_decider")
@require_http_methods(["POST"])
def upload_decision_minutes(request: HttpRequest, session_id) -> JsonResponse:
    request_id = request.headers.get("X-Request-ID", "")
    try:
        document = store_decision_minutes(
            request.FILES.get("file"),
            tenant_id=request.tenant_id,
            session_id=session_id,
            uploaded_by=getattr(request.user, "id", None),
        )
    except AssessmentDocumentError as exc:
        return JsonResponse(
            api_error(exc.code, exc.message, request_id=request_id, http_status=exc.status),
            status=exc.status,
        )
    return JsonResponse(api_success(data={
        "document": {
            "id": str(document.id),
            "filename": document.original_filename,
            "sizeBytes": document.size_bytes,
            "sha256": document.sha256,
            "sealedAt": document.sealed_at.isoformat(),
        }
    }, request_id=request_id), status=201)


@require_assessment_permission(
    ("hr.assessment.final_decider", "hr.assessment.auditor")
)
@require_http_methods(["GET"])
def download_decision_minutes(request: HttpRequest, session_id, document_id):
    try:
        purpose = str(request.headers.get("X-HR-Access-Reason", "") or "").strip()
        if not purpose:
            raise AssessmentDocumentError(
                "ASSESSMENT_DOCUMENT_ACCESS_REASON_REQUIRED",
                "下载考核纪要前请填写查阅事由",
                status=400,
            )
        if len(purpose) > 500:
            raise AssessmentDocumentError(
                "ASSESSMENT_DOCUMENT_ACCESS_REASON_INVALID",
                "查阅事由不能超过 500 个字符",
                status=400,
            )
        document = resolve_decision_minutes(
            tenant_id=request.tenant_id,
            session_id=session_id,
            document_id=document_id,
        )
        from django.core.files.storage import default_storage

        stream = default_storage.open(document.storage_key, "rb")
        try:
            HrAssessmentDocumentAccessAudit.objects.create(
                tenant_id=request.tenant_id,
                document=document,
                actor_user_id=request.user.id,
                purpose=purpose,
                request_id=str(request.headers.get("X-Request-ID", "") or "")[:128],
            )
        except Exception as exc:
            stream.close()
            raise AssessmentDocumentError(
                "ASSESSMENT_DOCUMENT_AUDIT_UNAVAILABLE",
                "考核文件访问审计暂时不可用，请稍后重试",
                status=503,
            ) from exc
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=document.original_filename,
            content_type=document.content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
    except AssessmentDocumentError as exc:
        return JsonResponse(
            api_error(exc.code, exc.message, http_status=exc.status),
            status=exc.status,
        )
