"""HR12 考核管理页面视图。"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.permissions import ASSESSMENT_PERMISSIONS
from hr_assessment.models import (
    HrAssessmentArchivePackage,
    HrAssessmentCase,
    HrAssessmentCycle,
    HrAssessmentPopulationSnapshot,
    HrEthicsAssessmentCase,
    HrFinalAssessmentResult,
    HrReviewerAssignment,
)


SECTIONS = {
    "overview": "考核管理总览",
    "policies": "制度与指标",
    "goals": "目标任务与平时考核",
    "annual": "年度考核",
    "term": "聘期考核",
    "ethics": "师德与专项考核",
    "review": "评议与审定",
    "archive": "结果与考核档案",
}


def _can_view_assessment(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return any(user.has_perm(code) for code, _label in ASSESSMENT_PERMISSIONS)


@login_required
def workspace(request, section="overview"):
    if not _can_view_assessment(request.user):
        raise PermissionDenied("没有考核管理访问权限")

    tenant_id = resolve_tenant_from_assignment(request)
    title = SECTIONS.get(section, "考核管理")
    if tenant_id is None:
        return render(
            request,
            "hr_assessment/workspace.html",
            {
                "section": section,
                "section_title": title,
                "access_error": "请选择当前学校后再进入考核管理。",
            },
            status=403,
        )

    cycles = HrAssessmentCycle.objects.filter(tenant_id=tenant_id)
    current_cycle = (
        cycles.filter(lifecycle_status__in=["PUBLISHED", "ACTIVE", "IN_PROGRESS", "OPEN"])
        .order_by("-start_at", "-created_at")
        .first()
        or cycles.order_by("-start_at", "-created_at").first()
    )
    population = HrAssessmentPopulationSnapshot.objects.filter(
        tenant_id=tenant_id, included=True, excluded=False,
    )
    if current_cycle:
        population = population.filter(cycle=current_cycle)
    participant_count = population.count()
    results = HrFinalAssessmentResult.objects.filter(tenant_id=tenant_id)
    if current_cycle:
        results = results.filter(cycle_id=current_cycle.id)
    finalized_count = results.filter(status="FINALIZED").count()
    completion_rate = (
        round(finalized_count / participant_count * 100)
        if participant_count
        else None
    )
    pending_review = HrReviewerAssignment.objects.filter(
        tenant_id=tenant_id, status="PENDING",
    ).count()
    ethics_abnormal = HrEthicsAssessmentCase.objects.filter(tenant_id=tenant_id).exclude(
        gate_status__in=["PASS", "CLEAR", "APPROVED"],
    ).count()
    pending_archive = HrFinalAssessmentResult.objects.filter(
        tenant_id=tenant_id, status="FINALIZED",
    ).exclude(archives__archive_status="ARCHIVED").distinct().count()
    summary = {
        "cycle_name": current_cycle.name if current_cycle else "未启动",
        "participant_count": participant_count,
        "completion_display": f"{completion_rate}%" if completion_rate is not None else "—",
        "pending_review": pending_review,
        "ethics_abnormal": ethics_abnormal,
        "pending_archive": pending_archive,
    }

    return render(
        request,
        "hr_assessment/workspace.html",
        {
            "section": section,
            "section_title": title,
            "tenant_id": tenant_id,
            "summary": summary,
        },
    )


# 保留旧函数名，避免历史反向引用失效。
def index(request):
    return workspace(request, "overview")
