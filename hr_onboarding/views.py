"""
hr_onboarding/views.py

HR05 页面视图（Django Template 渲染，数据走 JSON API，模板薄）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_onboarding.permissions import require_hr05_permission


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_prehires(request):
    """HR05-01 待报到人员列表（数据由 /api/hr/v1/onboarding/cases 提供）。"""
    return render(request, "hr/onboarding/prehires/list.html")


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_case_detail(request, case_id):
    """HR05-01 case 详情页（Tabs：报到准备/个人资料/材料/岗位/Portal/历史）。"""
    return render(request, "hr/onboarding/prehires/detail.html", {"case": {"id": case_id}})


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_reporting(request):
    """HR05-02 报到登记列表（数据由 /api/hr/v1/onboarding/cases 提供）。"""
    return render(request, "hr/onboarding/reporting/checkin.html", {"case": {}})


@login_required
@require_hr05_permission("hr05.report.checkin")
def hr05_report_checkin(request, case_id):
    """HR05-02 单 case 报到登记页（三栏：报到事实/组织岗位/生效前闸门）。"""
    return render(request, "hr/onboarding/reporting/checkin.html", {"case": {"id": case_id}})


@login_required
@require_hr05_permission("hr05.material.review")
def hr05_material_workspace(request):
    """HR05-03 材料核验工作台（三栏证据工作台）。"""
    return render(request, "hr/onboarding/materials/workspace.html", {"stats": {}})


@login_required
@require_hr05_permission("hr05.task.manage")
def hr05_collaboration_center(request):
    """HR05-04 协同任务中心（矩阵 + 我的任务）。"""
    return render(request, "hr/onboarding/collaboration/center.html", {"stats": {}, "my_tasks": []})


@login_required
@require_hr05_permission("hr05.probation.manage")
def hr05_probation_list(request):
    """HR05-05 试用转正列表（统计 + 表格）。"""
    return render(request, "hr/onboarding/probations/detail.html", {"stats": {}})


@login_required
@require_hr05_permission("hr05.probation.manage")
def hr05_probation_detail(request, probation_id):
    """HR05-05 试用详情（目标/自评/学院评价/审核/延长记录 + 决策栏）。"""
    return render(request, "hr/onboarding/probations/detail.html", {"probation": {"id": probation_id}})
