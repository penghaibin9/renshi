from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrTitleAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "职称评审总览",
    "applications": "职称申报",
    "eligibility": "资格审查",
    "materials": "材料与代表性成果",
    "experts": "专家与评委管理",
    "deliberation": "评议与表决",
    "publicity": "结果公示",
    "appeals": "异议与复核",
    "results": "正式职称结果",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "职称评审")
    # Screenshot C / production runtime: workspace_d keeps the C visual layer,
    # but executes its runtime inside the rendered content block so Horilla's
    # native sidebar toggle and the real dashboard API boot actually run.
    template_name = "hr_title/workspace_d.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrTitleAccessError as exc:
        return render(
            request,
            template_name,
            {"access_error": str(exc), "section": section, "section_title": title},
            status=403,
        )
    return render(
        request,
        template_name,
        {"tenant_id": tenant_id, "section": section, "section_title": title},
    )
