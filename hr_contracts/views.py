"""HR07 合同与聘用管理端页面。

这里只负责 presentation routing。所有正式合同事实仍通过 hr_contracts canonical API / Authority Service 读写。
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from hr_contracts.permissions import PERM_AGREEMENT_VIEW


SECTION_TITLES = {
    "ledger": "合同台账",
    "rules": "合同模板与规则",
    "signing": "签订与续签",
    "changes": "变更与解除",
    "risks": "聘期与到期预警",
}

SECTION_DESCRIPTIONS = {
    "ledger": "统一查看当前学校合同主档、状态、版本与有效期事实。",
    "rules": "管理合同类型、模板版本、适用范围、编号与期限规则。",
    "signing": "办理新签、首版签署、生效与后续续签流程。",
    "changes": "承接补充协议、合同变更、解除、终止与更正流程。",
    "risks": "集中处理合同到期、签署、续聘和跨域协同风险。",
}


@login_required
def contract_workspace(request, section="ledger"):
    if section not in SECTION_TITLES:
        section = "ledger"
    if not (request.user.is_superuser or request.user.has_perm(PERM_AGREEMENT_VIEW)):
        raise PermissionDenied("没有合同与聘用管理访问权限")

    return render(
        request,
        "hr_contracts/workspace.html",
        {
            "section": section,
            "section_title": SECTION_TITLES[section],
            "section_description": SECTION_DESCRIPTIONS[section],
            "section_titles": SECTION_TITLES,
        },
    )
