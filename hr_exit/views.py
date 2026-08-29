from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrExitAccessError, resolve_request_tenant
from .api import EFFECT_PERMISSION, HANDOVER_PERMISSION, MANAGE_PERMISSION
from .archive_registry import PERM_ARCHIVE_MANAGE, PERM_ARCHIVE_VIEW

SECTIONS = {
    "overview": "退休离校总览",
    "cases": "离校审批",
    "handover": "工作交接",
    "settlement": "最终结算",
    "retirement_precheck": "退休预审",
    "retirement_facts": "正式退休事实",
    "effects": "跨域生效协同",
    "archive": "正式离校档案",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "退休离校")
    template_name = "hr_exit/workspace.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrExitAccessError as exc:
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
            "can_manage": allowed(MANAGE_PERMISSION),
            "can_handover": allowed(HANDOVER_PERMISSION),
            "can_effect": allowed(EFFECT_PERMISSION),
            "can_archive_view": allowed(PERM_ARCHIVE_VIEW),
            "can_archive_manage": allowed(PERM_ARCHIVE_MANAGE),
        },
    )
