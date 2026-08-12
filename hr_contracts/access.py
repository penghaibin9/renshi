"""HR07 request access guard."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from hr_staff.context import resolve_tenant_from_request


VIEW_PERMISSION = "hr_contracts.view_hrcontractagreement"
CHANGE_PERMISSION = "hr_contracts.change_hrcontractcase"


def require_contract_access(request, *, write: bool = False) -> int:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("请先登录。")
    permission = CHANGE_PERMISSION if write else VIEW_PERMISSION
    if not user.is_superuser and not user.has_perm(permission):
        raise PermissionDenied("没有合同管理访问权限。")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise PermissionDenied("请选择当前学校后再进入合同管理。")
    return int(tenant_id)
