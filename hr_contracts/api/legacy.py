"""
hr_contracts/api/legacy.py

Legacy 页面接管（HR07 §127 / 00 §55）：
Authority 切换后，旧 `/payroll/contracts/*` 页面通过此视图 redirect/block。
"""

from __future__ import annotations

from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from hr_contracts.api.base import make_hr07_context
from hr_contracts.constants import AuthorityMode
from hr_contracts.models import HrContractAuthorityMode


def _authority_mode(request) -> str:
    try:
        ctx = make_hr07_context(request)
    except Exception:
        return AuthorityMode.LEGACY_CONTRACT_ONLY
    row = HrContractAuthorityMode.objects.filter(tenant_id=ctx.tenant_id).first()
    return row.mode if row else AuthorityMode.LEGACY_CONTRACT_ONLY


def legacy_contract_list(request):
    mode = _authority_mode(request)
    if mode == AuthorityMode.HR07_AUTHORITY:
        return HttpResponseRedirect(reverse("hr07-contracts-workbench"))
    # LEGACY / DUAL: 仍服务旧页面
    return HttpResponse("OK", status=200)  # 继续由原有 payroll 视图处理


@require_http_methods(["GET", "POST"])
def legacy_contract_create(request):
    mode = _authority_mode(request)
    if mode == AuthorityMode.HR07_AUTHORITY:
        return HttpResponseRedirect(reverse("hr07-signing"))
    return HttpResponse("OK", status=200)


@require_http_methods(["GET", "POST"])
def legacy_contract_edit(request, contract_id):
    mode = _authority_mode(request)
    if mode == AuthorityMode.HR07_AUTHORITY:
        # 禁止编辑 active 合同（正式 Authority 下）
        return HttpResponse("合同管理已迁移至 HR07，请在新系统操作", status=403)
    return HttpResponse("OK", status=200)
