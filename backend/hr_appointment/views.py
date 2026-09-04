from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrAppointmentAccessError, resolve_request_tenant
from .decision_api import DECISION_PERMISSION
from .permissions import (
    APPLICATION_PERMISSION,
    EFFECT_PERMISSION,
    MANAGE_PERMISSION,
    PUBLICITY_PERMISSION,
    REVIEW_PERMISSION,
    FACT_CORRECT_PERMISSION,
)
from .term_api import TERM_PERMISSION

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
    template_name = "hr_appointment/workspace.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrAppointmentAccessError as exc:
        return render(
            request,
            template_name,
            {"access_error": str(exc), "section": section, "section_title": title},
            status=403,
        )
    user = request.user

    def allowed(permission):
        return bool(user.is_superuser or user.has_perm(permission))

    return render(
        request,
        template_name,
        {
            "tenant_id": tenant_id,
            "section": section,
            "section_title": title,
            "can_apply": allowed(APPLICATION_PERMISSION),
            "can_manage": allowed(MANAGE_PERMISSION),
            "can_review": allowed(REVIEW_PERMISSION),
            "can_publicity": allowed(PUBLICITY_PERMISSION),
            "can_decide": allowed(DECISION_PERMISSION),
            "can_effect": allowed(EFFECT_PERMISSION),
            "can_term": allowed(TERM_PERMISSION),
            "can_fact_correct": allowed(FACT_CORRECT_PERMISSION),
        },
    )
