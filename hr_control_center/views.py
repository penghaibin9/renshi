"""
hr_control_center/views.py

HR01 页面视图（Django Template 渲染，数据走 JSON API）。
模板薄、组件公共化；页面本身不做数据计算。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_control_center.permissions import require_hr_permission


@login_required
@require_hr_permission("hr.dashboard.view")
def hr_overview(request):
    """HR01-01 人事总览页面。"""
    return render(request, "hr/overview.html")


@login_required
@require_hr_permission("hr.dashboard.todo.view")
def hr_todos(request):
    """HR01-02 我的待办页面。"""
    return render(request, "hr/todos.html")


@login_required
@require_hr_permission("hr.dashboard.alert.view")
def hr_alerts(request):
    """HR01-03 人事预警页面。"""
    return render(request, "hr/alerts.html")


@login_required
@require_hr_permission("hr.dashboard.workforce.view")
def hr_workforce(request):
    """HR01-04 队伍结构页面。"""
    return render(request, "hr/workforce.html")


@login_required
@require_hr_permission("hr.dashboard.quick_action.use")
def hr_actions(request):
    """HR01-05 快捷办理页面。"""
    return render(request, "hr/actions.html")
