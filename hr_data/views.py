from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrDataAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "人事数据总览",
    "metrics": "指标口径中心",
    "population": "Population / Dimension",
    "asof": "历史时点 As-of",
    "quality": "数据质量中心",
    "exchange": "数据交换",
    "submissions": "正式报送",
    "corrections": "回执与更正",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "人事数据中心")
    template_name = "hr_data/workspace_v2.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrDataAccessError as exc:
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
