"""HR04 招聘与人才引进页面视图。"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from hr_recruitment.context import resolve_tenant_from_request
from hr_recruitment.models import (
    HrAssessmentEvent,
    HrBackgroundCheck,
    HrCandidateScoreSheet,
    HrEvaluatorAssignment,
    HrHiringPlanCycle,
    HrJobApplication,
    HrMedicalCheck,
    HrNoticeObjection,
    HrProposedHire,
    HrPublicNotice,
    HrQualificationReview,
    HrRecruitmentCampaign,
    HrRecruitmentHandoff,
    HrRecruitmentOffer,
    HrRecruitmentPosition,
    HrSelectionResultSnapshot,
)
from hr_recruitment.permissions import require_hr04_permission


APPLICATION_STATUS_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "已提交",
    "UNDER_REVIEW": "审核中",
    "RETURNED": "退回补正",
    "RESUBMITTED": "重新提交",
    "QUALIFIED": "资格通过",
    "DISQUALIFIED": "资格不通过",
    "ASSESSMENT_PENDING": "待考试/面试",
    "ASSESSING": "考试/面试中",
    "ASSESSMENT_PASSED": "选拔通过",
    "ASSESSMENT_FAILED": "选拔未通过",
    "MEDICAL_PENDING": "待体检",
    "MEDICAL_REVIEW": "体检复核",
    "BACKGROUND_PENDING": "待考察",
    "BACKGROUND_REVIEW": "考察中",
    "PROPOSED_HIRE": "拟录用",
    "PUBLIC_NOTICE": "公示中",
    "OFFER_PENDING": "待发录用通知",
    "OFFERED": "已发录用通知",
    "OFFER_ACCEPTED": "已接受录用",
    "OFFER_DECLINED": "已拒绝录用",
    "HANDOFF_TO_HR05": "已交接入职",
    "WITHDRAWN": "候选人撤回",
    "CANCELLED": "已取消",
}
EVENT_STATUS_ZH = {
    "DRAFT": "草稿",
    "SCHEDULED": "已排期",
    "IN_PROGRESS": "进行中",
    "COMPLETED": "已完成",
    "CANCELLED": "已取消",
}
COMPONENT_ZH = {
    "DOCUMENT_REVIEW": "材料评审",
    "WRITTEN_EXAM": "笔试",
    "TEACHING_DEMO": "试讲",
    "PROFESSIONAL_TEST": "专业测试",
    "SKILL_TEST": "技能测试",
    "INTERVIEW": "面试",
    "PSYCHOLOGICAL_TEST": "心理测评",
    "MEDICAL_CHECK": "体检",
    "BACKGROUND_CHECK": "考察/政审",
}
SHEET_STATUS_ZH = {
    "DRAFT": "待评分",
    "SUBMITTED": "已提交待锁定",
    "LOCKED": "已锁定",
    "VOID": "已作废",
    "REOPEN_REQUESTED": "申请重新评分",
    "REOPEN_APPROVED": "已批准重开",
}
CONFLICT_ZH = {
    "CLEAR": "无回避事项",
    "DECLARED": "专家主动申报",
    "DETECTED": "系统发现冲突",
    "RECUSED": "已回避",
    "OVERRIDDEN": "已授权例外",
}
MEDICAL_ZH = {"PENDING": "待体检", "FIT": "符合要求", "UNFIT": "不符合要求", "RECHECK": "需复检", "NOT_REQUIRED": "无需体检"}
BACKGROUND_ZH = {"PENDING": "待考察", "PASS": "考察通过", "FAIL": "考察不通过", "NOT_REQUIRED": "无需考察"}


def _tenant_or_403(request):
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise PermissionDenied("请选择当前学校后再进入招聘管理")
    return int(tenant_id)


def _can_any(user, *codes):
    return user.is_superuser or any(user.has_perm(code) for code in codes)


def _overview_context(tenant_id):
    now = timezone.now()
    today = timezone.localdate()
    cycles = HrHiringPlanCycle.objects.filter(tenant_id=tenant_id)
    campaigns = HrRecruitmentCampaign.objects.filter(tenant_id=tenant_id)
    positions = HrRecruitmentPosition.objects.filter(tenant_id=tenant_id)
    apps = HrJobApplication.objects.filter(tenant_id=tenant_id)
    events = HrAssessmentEvent.objects.filter(tenant_id=tenant_id)
    proposed = HrProposedHire.objects.filter(tenant_id=tenant_id)
    notices = HrPublicNotice.objects.filter(tenant_id=tenant_id)
    objections = HrNoticeObjection.objects.filter(tenant_id=tenant_id)
    offers = HrRecruitmentOffer.objects.filter(tenant_id=tenant_id)
    handoffs = HrRecruitmentHandoff.objects.filter(tenant_id=tenant_id)

    processing_apps = [
        "SUBMITTED", "UNDER_REVIEW", "RETURNED", "RESUBMITTED", "QUALIFIED",
        "ASSESSMENT_PENDING", "ASSESSING", "ASSESSMENT_PASSED", "MEDICAL_PENDING",
        "MEDICAL_REVIEW", "BACKGROUND_PENDING", "BACKGROUND_REVIEW", "PROPOSED_HIRE",
        "PUBLIC_NOTICE", "OFFER_PENDING", "OFFERED", "OFFER_ACCEPTED",
    ]
    summary = {
        "active_plan_cycles": cycles.exclude(status__in=["CLOSED", "REJECTED"]).count(),
        "open_campaigns": campaigns.filter(status__in=["PUBLISHED", "OPEN", "RESULT_PROCESSING"]).count(),
        "open_positions": positions.filter(status__in=["READY", "OPEN", "SELECTION", "PROPOSED_HIRE", "PARTIALLY_FILLED"]).count(),
        "processing_apps": apps.filter(is_active=True, canonical_status__in=processing_apps).count(),
        "qualification_queue": apps.filter(canonical_status__in=["SUBMITTED", "UNDER_REVIEW", "RETURNED", "RESUBMITTED"]).count(),
        "assessment_queue": apps.filter(canonical_status__in=["QUALIFIED", "ASSESSMENT_PENDING", "ASSESSING"]).count(),
        "proposed_queue": proposed.exclude(approval_status__in=["REJECT", "WITHDRAW"]).count(),
        "handoff_done": handoffs.filter(status__in=["COMPLETED", "SUCCESS", "DONE"]).count(),
    }

    focus = []
    overdue = apps.filter(is_active=True, due_at__lt=now).exclude(
        canonical_status__in=["HANDOFF_TO_HR05", "WITHDRAWN", "CANCELLED", "ASSESSMENT_FAILED", "DISQUALIFIED"]
    ).count()
    if overdue:
        focus.append({"level": "danger", "title": f"{overdue} 份应聘申请已经超过办理时限", "desc": "优先确认当前责任人和所在环节，避免候选人长期停留在资格、面试或录用阶段。", "url": "/hr/recruitment/candidates", "action": "查看应聘者"})
    conflicts = HrEvaluatorAssignment.objects.filter(tenant_id=tenant_id, conflict_status__in=["DECLARED", "DETECTED"]).count()
    if conflicts:
        focus.append({"level": "danger", "title": f"{conflicts} 个专家回避事项待处理", "desc": "存在利益冲突的专家不能继续参与对应候选评分，先完成回避或有依据的例外审批。", "url": "/hr/recruitment/assessment", "action": "处理专家回避"})
    objections_open = objections.filter(status__in=["RECEIVED", "UNDER_REVIEW", "NEEDS_EVIDENCE"]).count()
    if objections_open:
        focus.append({"level": "warning", "title": f"{objections_open} 件公示异议尚未闭环", "desc": "公示异议处理完成前不能直接把拟录用结果交接到入职。", "url": "/hr/recruitment/proposed-hires", "action": "进入录用工作区"})
    expiring_offers = offers.filter(status__in=["ISSUED", "VIEWED"], expires_at__isnull=False, expires_at__gte=now).order_by("expires_at")[:20]
    expiring_count = sum(1 for item in expiring_offers if (item.expires_at - now).days <= 7)
    if expiring_count:
        focus.append({"level": "warning", "title": f"{expiring_count} 份录用通知 7 天内到期", "desc": "及时跟进候选人是否接受，并提前准备未接受情况下的递补或终止处理。", "url": "/hr/recruitment/proposed-hires", "action": "查看录用通知"})

    campaign_rows = []
    for row in campaigns.annotate(position_count=Count("positions")).order_by("-updated_at")[:12]:
        campaign_rows.append({
            "code": row.code,
            "title": row.title,
            "status": row.get_status_display(),
            "status_code": row.status,
            "positions": row.position_count,
            "open_at": row.application_open_at,
            "close_at": row.application_close_at,
        })

    application_rows = []
    for row in apps.select_related("candidate_id", "recruitment_position_id").order_by("due_at", "-updated_at")[:15]:
        application_rows.append({
            "no": row.application_no or str(row.id)[:8],
            "candidate": row.candidate_id.legal_name,
            "position": row.recruitment_position_id.post_catalog_name or "未命名招聘岗位",
            "organization": row.recruitment_position_id.organization_name or "—",
            "status": APPLICATION_STATUS_ZH.get(row.canonical_status, row.canonical_status),
            "status_code": row.canonical_status,
            "stage": row.workflow_stage_name or "按权威状态办理",
            "owner": row.current_owner_id or "待分派",
            "due_at": row.due_at,
        })

    return {
        "today": today,
        "summary": summary,
        "focus_items": focus,
        "campaign_rows": campaign_rows,
        "application_rows": application_rows,
        "notice_active": notices.filter(status="ACTIVE").count(),
        "offer_waiting": offers.filter(status__in=["APPROVED", "ISSUED", "VIEWED"]).count(),
    }


@login_required
def hr04_overview(request):
    if not _can_any(request.user, "hr04.campaign.view", "hr04.application.view", "hr04.proposed_hire.manage"):
        raise PermissionDenied("没有招聘管理访问权限")
    tenant_id = _tenant_or_403(request)
    return render(request, "hr/recruitment/workspace.html", _overview_context(tenant_id))


@login_required
@require_hr04_permission("hr04.assessment.manage")
def hr04_assessment(request):
    tenant_id = _tenant_or_403(request)
    today = timezone.localdate()
    events = HrAssessmentEvent.objects.filter(tenant_id=tenant_id)
    sheets = HrCandidateScoreSheet.objects.filter(tenant_id=tenant_id)
    evaluators = HrEvaluatorAssignment.objects.filter(tenant_id=tenant_id)
    medical = HrMedicalCheck.objects.filter(tenant_id=tenant_id)
    background = HrBackgroundCheck.objects.filter(tenant_id=tenant_id)
    snapshots = HrSelectionResultSnapshot.objects.filter(tenant_id=tenant_id)

    summary = {
        "today_events": events.filter(event_date=today).exclude(status="CANCELLED").count(),
        "upcoming_events": events.filter(event_date__gte=today, status="SCHEDULED").count(),
        "scoring_open": sheets.filter(status__in=["DRAFT", "SUBMITTED", "REOPEN_REQUESTED", "REOPEN_APPROVED"]).count(),
        "locked_scores": sheets.filter(status="LOCKED").count(),
        "conflicts": evaluators.filter(conflict_status__in=["DECLARED", "DETECTED"]).count(),
        "medical_pending": medical.filter(status__in=["PENDING", "RECHECK"]).count(),
        "background_pending": background.filter(status="PENDING").count(),
        "frozen_results": snapshots.values("recruitment_position_id", "snapshot_version").distinct().count(),
    }

    event_rows = []
    for row in events.select_related("component_id").annotate(
        participant_count=Count("participants", distinct=True),
        evaluator_count=Count("evaluators", distinct=True),
        sheet_count=Count("score_sheets", distinct=True),
    ).order_by("event_date", "start_time")[:40]:
        event_rows.append({
            "title": row.title,
            "component": COMPONENT_ZH.get(row.component_id.component_type, row.component_id.name),
            "date": row.event_date,
            "time": row.start_time,
            "mode": "线上" if row.mode == "ONLINE" else "现场",
            "location": row.online_url if row.mode == "ONLINE" else (row.location or "待安排"),
            "capacity": row.capacity,
            "participants": row.participant_count,
            "evaluators": row.evaluator_count,
            "sheets": row.sheet_count,
            "status": EVENT_STATUS_ZH.get(row.status, row.status),
            "status_code": row.status,
        })

    score_rows = []
    for row in sheets.select_related(
        "application_id__candidate_id", "application_id__recruitment_position_id", "event_id", "evaluator_id"
    ).order_by("status", "-updated_at")[:50]:
        score_rows.append({
            "candidate": row.application_id.candidate_id.legal_name,
            "position": row.application_id.recruitment_position_id.post_catalog_name or "未命名岗位",
            "event": row.event_id.title,
            "evaluator": row.evaluator_id.evaluator_name or str(row.evaluator_id.evaluator_staff_id),
            "status": SHEET_STATUS_ZH.get(row.status, row.status),
            "status_code": row.status,
            "score": row.total_score,
            "version": row.version,
        })

    conflict_rows = []
    for row in evaluators.filter(conflict_status__in=["DECLARED", "DETECTED", "RECUSED", "OVERRIDDEN"]).select_related("event_id").order_by("-created_at")[:30]:
        conflict_rows.append({
            "event": row.event_id.title,
            "evaluator": row.evaluator_name or str(row.evaluator_staff_id),
            "role": row.role or "评委",
            "status": CONFLICT_ZH.get(row.conflict_status, row.conflict_status),
            "status_code": row.conflict_status,
            "reason": row.recusal_reason or "—",
            "blind": row.blind_mode,
        })

    check_rows = []
    for row in medical.select_related("application_id__candidate_id", "application_id__recruitment_position_id").order_by("-created_at")[:20]:
        check_rows.append({"candidate": row.application_id.candidate_id.legal_name, "position": row.application_id.recruitment_position_id.post_catalog_name or "未命名岗位", "type": "体检", "status": MEDICAL_ZH.get(row.result or row.status, row.result or row.status), "time": row.scheduled_at})
    for row in background.select_related("application_id__candidate_id", "application_id__recruitment_position_id").order_by("-created_at")[:20]:
        check_rows.append({"candidate": row.application_id.candidate_id.legal_name, "position": row.application_id.recruitment_position_id.post_catalog_name or "未命名岗位", "type": "考察/政审", "status": BACKGROUND_ZH.get(row.result or row.status, row.result or row.status), "time": getattr(row, "completed_at", None)})

    return render(request, "hr/recruitment/assessment/workspace.html", {
        "today": today,
        "summary": summary,
        "event_rows": event_rows,
        "score_rows": score_rows,
        "conflict_rows": conflict_rows,
        "check_rows": check_rows,
    })


@login_required
@require_hr04_permission("hr04.campaign.view")
def hr04_campaigns(request):
    return render(request, "hr/recruitment/campaigns/console.html")


@login_required
@require_hr04_permission("hr04.plan.view")
def hr04_plans(request):
    return render(request, "hr/recruitment/plans/plans.html")


@login_required
@require_hr04_permission("hr04.application.view")
def hr04_candidates(request):
    return render(request, "hr/recruitment/candidates/candidates.html")


@login_required
@require_hr04_permission("hr04.qualification.review")
def hr04_qualification(request):
    return render(request, "hr/recruitment/qualification/qualification.html")


@login_required
@require_hr04_permission("hr04.proposed_hire.manage")
def hr04_proposed_hires(request):
    return render(request, "hr/recruitment/proposed_hires/proposed.html")
