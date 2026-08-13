from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrAppointmentAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "岗位聘任总览",
    "policies": "聘任制度",
    "quota": "岗位额度快照",
    "competitions": "竞聘批次",
    "applications": "竞聘申报",
    "ranking": "评议排序",
    "publicity": "拟聘公示",
    "appointments": "正式岗位聘任",
    "term_changes": "聘期变更",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "岗位聘任")
    # workspace_live owns ranking/publicity real workflows;
    # workspace_term adds term/renewal/change governance while preserving the
    # hard boundary that approval is not an HR03/appointment effect.
    template_name = "hr_appointment/workspace_term.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrAppointmentAccessError as exc:
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
