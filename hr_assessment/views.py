"""HR12 考核管理页面视图。"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from hr_assessment.context import resolve_tenant_from_assignment
from hr_assessment.permissions import ASSESSMENT_PERMISSIONS


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

    return render(
        request,
        "hr_assessment/workspace.html",
        {
            "section": section,
            "section_title": title,
            "tenant_id": tenant_id,
        },
    )


# 保留旧函数名，避免历史反向引用失效。
def index(request):
    return workspace(request, "overview")
