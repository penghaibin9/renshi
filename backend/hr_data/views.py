from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrDataAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "人事数据总览",
    "metrics": "指标口径中心",
    "population": "标准报表与自助分析",
    "asof": "历史时点分析",
    "quality": "数据质量中心",
    "exchange": "数据交换",
    "submissions": "正式报送",
    "corrections": "回执与更正",
}

ACTION_PERMISSIONS = {
    "can_define": "hr.data.define",
    "can_asof": "hr.data.asof",
    "can_quality": "hr.data.quality",
    "can_submit": "hr.data.submit",
    "can_approve": "hr.data.approve",
    "can_receipt": "hr.data.receipt",
    "can_exchange": "hr.data.exchange",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "人事数据中心")
    template_name = "hr_data/workspace_v2.html"
    try:
        resolve_request_tenant(request)
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
        {
            "section": section,
            "section_title": title,
            **{
                key: bool(request.user.is_superuser or request.user.has_perm(permission))
                for key, permission in ACTION_PERMISSIONS.items()
            },
        },
    )
