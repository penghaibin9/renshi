"""
hr10_development/views.py

HR10 页面视图（管理端 UI）。
渲染中文模板；数据经 selectors/API 获取。
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_GET

from horilla.horilla_middlewares import get_selected_company
from hr10_development.permissions import require_hr10_permission
from hr10_development.selectors.plan_selector import PlanSelector


def _selected_tenant_id() -> int:
    """Resolve the canonical web tenant and reject union/missing scope."""
    selected = get_selected_company()
    if selected in (None, "", "all"):
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    try:
        return int(selected)
    except (TypeError, ValueError) as exc:
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED") from exc


@require_GET
@require_hr10_permission("hr.development.plan.view")
def plan_center(request):
    """发展计划工作台首页。"""
    tenant_id = _selected_tenant_id()
    plans = PlanSelector.list_plans(tenant_id=tenant_id)
    stats = PlanSelector.get_summary_stats(tenant_id=tenant_id)
    return render(request, "hr/development/plans.html", {
        "plans": plans,
        "stats": stats,
        "page_title": "教师发展计划",
    })


@require_GET
@require_hr10_permission("hr.development.program.view")
def program_center(request):
    """培训项目首页。"""
    return render(request, "hr/development/programs.html", {
        "page_title": "培训项目",
    })


@require_GET
@require_hr10_permission("hr.development.request.view")
def request_center(request):
    """培训报名与审批首页。"""
    return render(request, "hr/development/requests.html", {
        "page_title": "培训报名与审批",
    })


@require_GET
@require_hr10_permission("hr.development.practice.view")
def practice_center(request):
    """企业实践首页。"""
    return render(request, "hr/development/practice.html", {
        "page_title": "企业实践项目",
    })


@require_GET
@require_hr10_permission("hr.development.record.view")
def development_record(request, staff_id):
    """教师发展档案。"""
    return render(request, "hr/development/record.html", {
        "staff_id": staff_id,
        "page_title": "教师发展档案",
    })


@require_GET
@require_hr10_permission("hr.development.analytics.read")
def development_dashboard(request):
    """发展 Dashboard。"""
    return render(request, "hr/development/dashboard.html", {
        "page_title": "教师发展总览",
    })
