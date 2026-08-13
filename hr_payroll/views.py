from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrPayrollAccessError, resolve_request_tenant

SECTIONS = {
    "overview": "薪酬总览",
    "profiles": "薪酬档案",
    "periods": "工资期间",
    "calculations": "工资核算",
    "rules": "薪资项目与规则",
    "allowances": "津贴与补贴",
    "social_security": "社保公积金与年金",
    "results": "正式薪酬结果",
    "payments": "支付与工资条",
    "reconciliation": "财务对账",
    "legacy_takeover": "旧 payroll 接管",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "薪酬福利")
    template_name = "hr_payroll/workspace_live.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
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