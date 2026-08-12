from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrPayrollAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "薪酬总览",
    "periods": "工资期间",
    "calculations": "工资核算",
    "rules": "薪资项目与规则",
    "benefits": "津补贴与五险一金",
    "payments": "支付与工资条",
    "reconciliation": "财务对账与旧系统接管",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "薪酬福利")
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return render(
            request,
            "hr_payroll/workspace.html",
            {"access_error": str(exc), "section": section, "section_title": title},
            status=403,
        )
    return render(
        request,
        "hr_payroll/workspace.html",
        {"tenant_id": tenant_id, "section": section, "section_title": title},
    )
