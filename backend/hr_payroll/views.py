from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .api import HrPayrollAccessError, resolve_request_tenant
from .authority_registry import (
    PERM_BENEFIT_MANAGE,
    PERM_CALCULATE,
    PERM_CHANGE_APPROVE,
    PERM_CHANGE_MANAGE,
    PERM_INPUT_MANAGE,
)

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
    "legacy_takeover": "历史工资对账",
}


@ensure_csrf_cookie
def workspace(request, section="overview"):
    title = SECTIONS.get(section, "薪酬福利")
    template_name = "hr_payroll/workspace.html"
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return render(
            request,
            template_name,
            {"access_error": str(exc), "section": section, "section_title": title},
            status=403,
        )
    user = request.user
    can_adjust = bool(user.is_superuser or user.has_perm("hr.payroll.adjust"))
    can_input = bool(user.is_superuser or user.has_perm(PERM_INPUT_MANAGE))
    can_calculate = bool(user.is_superuser or user.has_perm(PERM_CALCULATE))
    can_benefit_manage = bool(
        user.is_superuser or user.has_perm(PERM_BENEFIT_MANAGE)
    )
    can_change_manage = bool(
        user.is_superuser or user.has_perm(PERM_CHANGE_MANAGE)
    )
    can_change_approve = bool(
        user.is_superuser or user.has_perm(PERM_CHANGE_APPROVE)
    )
    return render(
        request,
        template_name,
        {
            "tenant_id": tenant_id,
            "section": section,
            "section_title": title,
            "can_adjust": can_adjust,
            "can_input": can_input,
            "can_calculate": can_calculate,
            "can_benefit_manage": can_benefit_manage,
            "can_change_manage": can_change_manage,
            "can_change_approve": can_change_approve,
        },
    )
