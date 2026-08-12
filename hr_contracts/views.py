"""HR07 合同管理页面视图。"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from hr_contracts.access import require_contract_access
from hr_contracts.selectors import contract_dashboard


SECTION_TITLES = {
    "overview": "合同管理工作台",
    "agreements": "合同主档",
    "signing": "合同签订",
    "renewals": "合同续签",
    "changes": "合同变更",
    "terminations": "解除与终止",
    "versions": "合同版本历史",
}


@login_required
def workspace(request, section="overview"):
    if section not in SECTION_TITLES:
        section = "overview"
    try:
        tenant_id = require_contract_access(request)
    except PermissionDenied as exc:
        return render(
            request,
            "hr_contracts/workspace.html",
            {
                "section": section,
                "section_title": SECTION_TITLES[section],
                "access_error": str(exc),
            },
            status=403,
        )

    data = contract_dashboard(tenant_id)
    cases = data["cases"]
    if section == "signing":
        section_cases = [x for x in cases if x["case_type_code"] == "SIGN"]
    elif section == "renewals":
        section_cases = [x for x in cases if x["case_type_code"] == "RENEW"]
    elif section == "changes":
        section_cases = [x for x in cases if x["case_type_code"] == "CHANGE"]
    elif section == "terminations":
        section_cases = [x for x in cases if x["case_type_code"] == "TERMINATE"]
    else:
        section_cases = cases

    focus_items = []
    summary = data["summary"]
    if summary["effect_errors"]:
        focus_items.append({
            "level": "danger",
            "title": f"{summary['effect_errors']} 个合同案件生效失败",
            "desc": "审批通过不等于合同已经生效，先处理跨域生效错误再关闭案件。",
            "url": "/hr/contracts/agreements/",
            "action": "查看合同主档",
        })
    if summary["pending_signature"]:
        focus_items.append({
            "level": "warning",
            "title": f"{summary['pending_signature']} 份合同待签署",
            "desc": "确认条款、版本和签署文件后，再进入正式生效阶段。",
            "url": "/hr/contracts/signing/",
            "action": "进入签订工作区",
        })
    if summary["expiring_90"]:
        focus_items.append({
            "level": "warning",
            "title": f"{summary['expiring_90']} 份合同 90 天内到期",
            "desc": "提前发起续签或到期处理，避免出现合同到期但聘用关系仍未处理。",
            "url": "/hr/contracts/renewals/",
            "action": "进入续签工作区",
        })
    if summary["waiting_effect"]:
        focus_items.append({
            "level": "info",
            "title": f"{summary['waiting_effect']} 份合同已签署待生效",
            "desc": "签字完成后仍要等待合同版本正式生效，不能直接当作履行中合同。",
            "url": "/hr/contracts/agreements/",
            "action": "查看待生效合同",
        })

    return render(
        request,
        "hr_contracts/workspace.html",
        {
            "tenant_id": tenant_id,
            "section": section,
            "section_title": SECTION_TITLES[section],
            "summary": summary,
            "agreements": data["agreements"],
            "cases": section_cases,
            "versions": data["versions"],
            "focus_items": focus_items,
            "today": data["today"],
        },
    )
