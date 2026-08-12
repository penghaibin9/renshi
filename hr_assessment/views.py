"""HR12 考核管理页面视图。"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.models import (
    HrAnnualAssessmentCase,
    HrAssessmentArchivePackage,
    HrAssessmentCase,
    HrAssessmentCycle,
    HrAssessmentDecisionSession,
    HrAssessmentGoal,
    HrAssessmentGoalPlan,
    HrAssessmentObjection,
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
    HrEthicsAssessmentCase,
    HrFinalAssessmentResult,
    HrGoalCheckIn,
    HrIndicatorDefinition,
    HrRatingScaleVersion,
    HrRoutineAssessmentEntry,
    HrTermAssessmentCase,
)
from hr_assessment.permissions import ASSESSMENT_PERMISSIONS


SECTIONS = {
    "overview": "考核管理工作台",
    "policies": "制度、指标与考核周期",
    "goals": "目标任务与平时考核",
    "annual": "年度考核",
    "term": "聘期考核",
    "ethics": "师德与专项考核",
    "review": "评议、校准与审定",
    "archive": "结果、申诉与考核档案",
}
STATUS_ZH = {
    "DRAFT": "草稿",
    "PUBLISHED": "已发布",
    "ACTIVE": "有效",
    "OPEN": "进行中",
    "CLOSED": "已关闭",
    "SUBMITTED": "已提交",
    "UNDER_REVIEW": "审核中",
    "REVIEWING": "评议中",
    "RETURNED": "退回修改",
    "APPROVED": "已批准",
    "FINALIZED": "已审定",
    "ARCHIVED": "已归档",
    "COMPLETED": "已完成",
    "CANCELLED": "已取消",
    "REVIEW_REQUIRED": "需要师德复核",
    "PASS": "通过",
    "FAIL": "不通过",
}
TYPE_ZH = {"ANNUAL": "年度考核", "TERM": "聘期考核", "SPECIAL": "专项考核", "ETHICS": "师德考核"}


def _can_view(user):
    return user.is_superuser or any(user.has_perm(code) for code, _label in ASSESSMENT_PERMISSIONS)


def _zh(value):
    return STATUS_ZH.get(value, value or "—")


@login_required
def workspace(request, section="overview"):
    if not _can_view(request.user):
        raise PermissionDenied("没有考核管理访问权限")
    if section not in SECTIONS:
        section = "overview"

    tenant_id = resolve_tenant_from_assignment(request)
    if not tenant_id:
        return render(
            request,
            "hr_assessment/workspace.html",
            {"section": section, "section_title": SECTIONS[section], "access_error": "请选择当前学校后再进入考核管理。"},
            status=403,
        )
    tenant_id = int(tenant_id)

    policies = HrAssessmentPolicyPack.objects.filter(tenant_id=tenant_id)
    policy_versions = HrAssessmentPolicyVersion.objects.filter(tenant_id=tenant_id)
    indicators = HrIndicatorDefinition.objects.filter(tenant_id=tenant_id)
    scales = HrRatingScaleVersion.objects.filter(tenant_id=tenant_id)
    cycles = HrAssessmentCycle.objects.filter(tenant_id=tenant_id)
    goals = HrAssessmentGoal.objects.filter(tenant_id=tenant_id)
    goal_plans = HrAssessmentGoalPlan.objects.filter(tenant_id=tenant_id)
    checkins = HrGoalCheckIn.objects.filter(goal_assignment__tenant_id=tenant_id)
    routine = HrRoutineAssessmentEntry.objects.filter(tenant_id=tenant_id)
    cases = HrAssessmentCase.objects.filter(tenant_id=tenant_id)
    annual_cases = HrAnnualAssessmentCase.objects.filter(tenant_id=tenant_id)
    term_cases = HrTermAssessmentCase.objects.filter(tenant_id=tenant_id)
    ethics_cases = HrEthicsAssessmentCase.objects.filter(tenant_id=tenant_id)
    decisions = HrAssessmentDecisionSession.objects.filter(tenant_id=tenant_id)
    results = HrFinalAssessmentResult.objects.filter(tenant_id=tenant_id)
    objections = HrAssessmentObjection.objects.filter(tenant_id=tenant_id)
    archives = HrAssessmentArchivePackage.objects.filter(tenant_id=tenant_id)

    summary = {
        "published_policies": policy_versions.filter(status="PUBLISHED").count(),
        "active_indicators": indicators.filter(is_active=True).count(),
        "active_cycles": cycles.exclude(lifecycle_status__in=["CLOSED", "CANCELLED", "ARCHIVED"]).count(),
        "open_goals": goals.exclude(status__in=["CLOSED", "CANCELLED", "ARCHIVED"]).count(),
        "annual_cases": annual_cases.count(),
        "term_cases": term_cases.count(),
        "ethics_review": ethics_cases.filter(gate_status="REVIEW_REQUIRED").count(),
        "final_results": results.filter(status="FINALIZED").count(),
    }

    focus = []
    open_cases = cases.exclude(status__in=["FINALIZED", "ARCHIVED", "CANCELLED", "CLOSED"]).count()
    if open_cases:
        focus.append({"level": "info", "title": f"{open_cases} 个考核对象仍在办理", "desc": "先看当前周期和评议阶段，避免对象长期停留在未完成状态。", "url": "/hr/assessments/annual/", "action": "查看考核案件"})
    ethics_count = summary["ethics_review"]
    if ethics_count:
        focus.append({"level": "danger", "title": f"{ethics_count} 个师德 Gate 需要人工复核", "desc": "师德结论必须来自独立事实和授权复核，不能从普通绩效分数自动推断。", "url": "/hr/assessments/ethics/", "action": "进入师德复核"})
    open_objections = objections.exclude(status__in=["RESOLVED", "CLOSED", "REJECTED"]).count()
    if open_objections:
        focus.append({"level": "warning", "title": f"{open_objections} 件考核异议尚未结案", "desc": "正式结果不能直接原地覆盖，异议改变结果时必须生成结果修订历史。", "url": "/hr/assessments/archive/", "action": "处理结果异议"})
    pending_archives = archives.exclude(archive_status__in=["ARCHIVED", "COMPLETED"]).count()
    if pending_archives:
        focus.append({"level": "warning", "title": f"{pending_archives} 份结果档案等待归档", "desc": "归档前检查政策版本、对象快照、证据、评议、审定和结果告知是否完整。", "url": "/hr/assessments/archive/", "action": "进入结果档案"})

    rows = []
    secondary_rows = []
    if section in ("overview", "policies"):
        for row in policies.order_by("code")[:40]:
            current = policy_versions.filter(policy_pack=row).order_by("-version_no").first()
            rows.append({"primary": row.name, "secondary": f"{row.code} · {row.assessment_domain}", "middle": f"第 {current.version_no} 版" if current else "尚无版本", "status": _zh(current.status) if current else "未发布", "status_code": current.status if current else "DRAFT"})
        for row in cycles.order_by("-start_at")[:30]:
            secondary_rows.append({"primary": row.name, "secondary": f"{TYPE_ZH.get(row.assessment_type, row.assessment_type)} · {row.cycle_no}", "middle": f"{row.start_at:%Y-%m-%d} 至 {row.end_at:%Y-%m-%d}", "status": _zh(row.lifecycle_status), "status_code": row.lifecycle_status})
    elif section == "goals":
        for row in goal_plans.order_by("-created_at")[:40]:
            rows.append({"primary": row.name, "secondary": f"{TYPE_ZH.get(row.goal_type, row.goal_type)}目标计划", "middle": f"{row.goals.count()} 个目标", "status": _zh(row.status), "status_code": row.status})
        for row in routine.order_by("-period_end", "-created_at")[:30]:
            secondary_rows.append({"primary": f"人员 {row.staff_id}", "secondary": f"{row.period_start} 至 {row.period_end} · {row.category or '平时考核'}", "middle": row.observation[:80] or "无文字记录", "status": _zh(row.status), "status_code": row.status})
    elif section == "annual":
        for row in annual_cases.select_related("subject_snapshot", "cycle").order_by("-business_year")[:50]:
            snap = row.subject_snapshot
            rows.append({"primary": snap.display_name if snap else f"人员 {row.staff_id}", "secondary": f"{row.business_year or '—'} 年度 · {(snap.org_name if snap else '')}", "middle": row.cycle.name if row.cycle else "未关联周期", "status": _zh(row.status), "status_code": row.status})
    elif section == "term":
        for row in term_cases.select_related("subject_snapshot", "cycle").order_by("-term_end")[:50]:
            snap = row.subject_snapshot
            rows.append({"primary": snap.display_name if snap else f"人员 {row.staff_id}", "secondary": f"聘期 {row.term_start} 至 {row.term_end}", "middle": snap.position_name if snap else "—", "status": _zh(row.status), "status_code": row.status})
    elif section == "ethics":
        for row in ethics_cases.select_related("subject_snapshot", "cycle").order_by("-decided_at")[:50]:
            snap = row.subject_snapshot
            rows.append({"primary": snap.display_name if snap else f"人员 {row.staff_id}", "secondary": snap.org_name if snap else "—", "middle": row.gate_reason_code or "等待师德事实复核", "status": _zh(row.gate_status), "status_code": row.gate_status})
    elif section == "review":
        for row in decisions.order_by("-meeting_at")[:40]:
            rows.append({"primary": "集体审定会", "secondary": str(row.id)[:8], "middle": row.meeting_at.strftime("%Y-%m-%d %H:%M") if row.meeting_at else "会议时间未设置", "status": _zh(row.status), "status_code": row.status})
    elif section == "archive":
        for row in results.order_by("-finalized_at")[:50]:
            rows.append({"primary": f"{TYPE_ZH.get(row.assessment_type, row.assessment_type)}结果", "secondary": f"Case {str(row.case_id)[:8]} · 版本 {row.result_version_no}", "middle": f"档次 {row.grade_code} · 分数 {row.calculated_score if row.calculated_score is not None else '—'}", "status": _zh(row.status), "status_code": row.status})
        for row in objections.order_by("-submitted_at")[:30]:
            secondary_rows.append({"primary": "结果异议/申诉", "secondary": f"结果 {str(row.result_id)[:8]} · {row.submitted_at:%Y-%m-%d}", "middle": row.reason[:80], "status": _zh(row.status), "status_code": row.status})

    return render(request, "hr_assessment/workspace.html", {
        "section": section,
        "section_title": SECTIONS[section],
        "summary": summary,
        "focus_items": focus,
        "rows": rows,
        "secondary_rows": secondary_rows,
        "scale_count": scales.count(),
        "indicator_count": indicators.filter(is_active=True).count(),
        "checkin_count": checkins.count(),
    })


def index(request):
    return workspace(request, "overview")
