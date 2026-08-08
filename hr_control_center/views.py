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
