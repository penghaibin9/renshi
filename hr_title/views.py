from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrTitleAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "评审总览",
    "applications": "申报与资格审查",
    "materials": "材料与代表性成果",
    "review": "专家评议与表决",
    "publicity": "公示与异议复核",
    "results": "正式职称结果",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    try:
        tenant_id = resolve_request_tenant(request)
    except HrTitleAccessError as exc:
        return render(request, "hr_title/workspace.html", {"access_error": str(exc), "section": section, "section_title": SECTIONS.get(section, "职称评审")}, status=403)
    return render(request, "hr_title/workspace.html", {"tenant_id": tenant_id, "section": section, "section_title": SECTIONS.get(section, "职称评审")})
