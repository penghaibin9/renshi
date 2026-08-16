"""
hr_structure/views.py

HR02 页面视图（薄模板，数据走 JSON API）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


SECTION_META = {
    "relations": {
        "title": "党政组织与业务关系",
        "subtitle": "维护行政隶属、党组织关系和跨机构业务关系，正式关系按生效日期留痕。",
    },
    "staffing-plans": {
        "title": "编制方案",
        "subtitle": "管理年度编制方案、版本状态、生效日期与后续审批动作。",
    },
    "post-catalogs": {
        "title": "岗位目录",
        "subtitle": "维护岗位标准、岗位类别、等级方案与岗位控制口径。",
    },
    "history": {
        "title": "组织岗位历史",
        "subtitle": "查看组织重组、撤并、调整等结构变更 Case 及其计划生效日期。",
    },
}


@login_required
def hr_organizations(request):
    """HR02-01 组织机构页面。"""
    return render(request, "hr/structure/organizations.html")


@login_required
def hr_structure_workspace(request, section):
    """HR02-02/03/04/06 统一管理工作区。"""
    meta = SECTION_META.get(section)
    if meta is None:
        section = "relations"
        meta = SECTION_META[section]
    return render(
        request,
        "hr/structure/workspace.html",
        {"section": section, "section_title": meta["title"], "section_subtitle": meta["subtitle"]},
    )


@login_required
def hr_positions(request):
    """HR02-05 岗位编制台账页面。"""
    return render(request, "hr/structure/positions.html")
