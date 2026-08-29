"""
hr10_development/views.py

HR10 页面视图（管理端 UI）。
渲染中文模板；数据经 selectors/API 获取。
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from horilla.horilla_middlewares import get_selected_company
from hr10_development.permissions import require_hr10_permission
from hr10_development.selectors.plan_selector import PlanSelector
from hr_staff.models import HrStaffMaster


def _selected_tenant_id() -> int:
    """Resolve the canonical web tenant and reject union/missing scope."""
    selected = get_selected_company()
    if selected in (None, "", "all"):
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    try:
        return int(selected)
    except (TypeError, ValueError) as exc:
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED") from exc


def _workspace_context(tenant_id: int, page: str, title: str) -> dict:
    staff = list(
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            legacy_employee_id__isnull=False,
        )
        .select_related("person_id")
        .order_by("person_id__legal_name", "staff_no")[:500]
    )
    staff_options = [
        {
            "id": item.legacy_employee_id,
            "label": f"{item.person_id.legal_name} · {item.staff_no}",
        }
        for item in staff
    ]
    return {
        "page_title": title,
        "hr10_page": page,
        "staff_options": staff_options,
        "record_url": (
            f"/hr/development/records/{staff_options[0]['id']}"
            if staff_options
            else ""
        ),
    }


@require_GET
@require_hr10_permission("hr.development.plan.view")
def plan_center(request):
    """发展计划工作台首页。"""
    tenant_id = _selected_tenant_id()
    plans = PlanSelector.list_plans(tenant_id=tenant_id)
    stats = PlanSelector.get_summary_stats(tenant_id=tenant_id)
    context = _workspace_context(tenant_id, "plans", "教师发展计划")
    context.update({
        "plans": plans,
        "stats": stats,
    })
    return render(request, "hr/development/plans.html", context)


@require_GET
@require_hr10_permission("hr.development.program.view")
def program_center(request):
    """培训项目首页。"""
    tenant_id = _selected_tenant_id()
    return render(
        request,
        "hr/development/programs.html",
        _workspace_context(tenant_id, "programs", "培训项目"),
    )


@require_GET
@require_hr10_permission("hr.development.request.view")
def request_center(request):
    """培训报名与审批首页。"""
    tenant_id = _selected_tenant_id()
    return render(
        request,
        "hr/development/requests.html",
        _workspace_context(tenant_id, "requests", "培训报名与审批"),
    )


@require_GET
@require_hr10_permission("hr.development.practice.view")
def practice_center(request):
    """企业实践首页。"""
    tenant_id = _selected_tenant_id()
    return render(
        request,
        "hr/development/practice.html",
        _workspace_context(tenant_id, "practice", "企业实践项目"),
    )


@require_GET
@require_hr10_permission("hr.development.record.view")
def development_record(request, staff_id):
    """教师发展档案。"""
    tenant_id = _selected_tenant_id()
    staff = (
        HrStaffMaster.objects.select_related("person_id")
        .filter(tenant_id=tenant_id, legacy_employee_id=staff_id)
        .first()
    )
    if staff is None:
        raise Http404("当前学校没有对应的教师发展档案")
    context = _workspace_context(tenant_id, "record", "教师发展档案")
    context.update(
        {
            "staff_id": staff_id,
            "staff_label": f"{staff.person_id.legal_name} · {staff.staff_no}",
        }
    )
    return render(request, "hr/development/record.html", context)


@require_GET
@require_hr10_permission("hr.development.analytics.read")
def development_dashboard(request):
    """发展 Dashboard。"""
    tenant_id = _selected_tenant_id()
    return render(
        request,
        "hr/development/dashboard.html",
        _workspace_context(tenant_id, "dashboard", "教师发展总览"),
    )
