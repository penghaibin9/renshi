"""HR12 Assessment — 基础 API 视图（生产级）。"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.db.models import Count
from django.http import HttpRequest, JsonResponse
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
from hr_assessment.models.result import (
    HrAssessmentArchivePackage,
    HrAssessmentDecisionSession,
    HrCalibrationSession,
    HrFinalAssessmentResult,
)
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
    return {
        "id": str(result.id),
        "caseId": str(result.case_id),
        "status": result.status,
        "gradeCode": result.grade_code,
        "displayGrade": result.display_grade_snapshot_json or {},
        "calculatedScore": str(result.calculated_score) if result.calculated_score is not None else None,
        "decisionReason": result.decision_reason or "",
        "decisionSessionId": str(result.decision_session_id) if result.decision_session_id else None,
        "finalizedAt": result.finalized_at.isoformat() if result.finalized_at else None,
        "finalizedBy": str(result.finalized_by) if result.finalized_by else None,
        "resultVersionNo": result.result_version_no,
        "contentHash": result.content_hash,
    }


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
    grade_code = str(payload.get("gradeCode") or "").strip().upper()
    if grade_code not in ANNUAL_GRADE_LABELS:
        return JsonResponse(api_error(
            "ASSESSMENT_GRADE_INVALID",
            "年度考核档次必须为优秀、合格、基本合格或不合格",
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
    score = None
    raw_score = payload.get("calculatedScore")
    if raw_score not in (None, ""):
        try:
            score = Decimal(str(raw_score))
        except (InvalidOperation, ValueError):
            return JsonResponse(api_error(
                "ASSESSMENT_SCORE_INVALID", "计算分必须为有效数字", request_id=request_id, http_status=400,
            ), status=400)
    try:
        result = AssessmentFinalizationService(
            tenant,
            actor_staff_id=getattr(request, "staff_id", None),
        ).finalize(
            case_id=case_id,
            payload=FinalResultInput(
                grade_code=grade_code,
                display_grade_snapshot={"zh-CN": ANNUAL_GRADE_LABELS[grade_code]},
                decision_reason=str(payload.get("decisionReason") or "年度考核工作台正式审定").strip(),
                decision_session_id=decision_session_id,
                calculated_score=score,
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
