"""
hr_recruitment/views.py

HR04 页面视图（Django Template 渲染，数据走 JSON API，模板薄）。
S1 阶段：招聘控制台占位页（数据接 HR04-02 后填充）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_recruitment.permissions import require_hr04_permission


@login_required
@require_hr04_permission("hr04.campaign.view")
def hr04_campaigns(request):
    """HR04 招聘控制台（默认入口 = HR04-02 招聘项目与岗位，总册 5.1）。"""
    return render(request, "hr/recruitment/campaigns/console.html")


@login_required
@require_hr04_permission("hr04.plan.view")
def hr04_plans(request):
    """HR04-01 年度用人计划页面。"""
    return render(request, "hr/recruitment/plans/plans.html")


@login_required
@require_hr04_permission("hr04.application.view")
def hr04_candidates(request):
    """HR04-03 人才库页面。"""
    return render(request, "hr/recruitment/candidates/candidates.html")


@login_required
@require_hr04_permission("hr04.qualification.review")
def hr04_qualification(request):
    """HR04-04 资格审查工作台页面。"""
    return render(request, "hr/recruitment/qualification/qualification.html")


@login_required
@require_hr04_permission("hr04.proposed_hire.manage")
def hr04_proposed_hires(request):
    """HR04-06 拟录用工作台页面。"""
    return render(request, "hr/recruitment/proposed_hires/proposed.html")
