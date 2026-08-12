from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrSelfAccessError, resolve_self_context

SECTIONS = {
    "overview": "我的人事服务",
    "services": "服务大厅",
    "todos": "我的待办",
    "progress": "办理进度",
    "files": "我的文件",
    "payslips": "我的工资条",
    "contracts": "我的合同",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "教职工服务")
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return render(
            request,
            "hr_self/workspace.html",
            {"access_error": str(exc), "section": section, "section_title": title},
            status=403,
        )
    return render(
        request,
        "hr_self/workspace.html",
        {"section": section, "section_title": title, "self_staff_id": str(context.staff_id)},
    )
