"""
hr_structure/scope.py

HR02 数据范围（总册 6.3）：
- SCHOOL / ORG_SUBTREE / ORGANIZATION / ASSIGNED_ORGS / READ_ONLY_SCHOOL
- 所有 selector 第一条件 tenant；禁止裸 `HrOrganization.objects.get(pk=id)`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hr_control_center.context import HrContextError


@dataclass(frozen=True)
class Hr02Scope:
    scope_type: str  # SCHOOL / ORG_SUBTREE / ORGANIZATION / ASSIGNED_ORGS / READ_ONLY_SCHOOL
    tenant_id: int
    org_id: Optional[int] = None  # ORG_SUBTREE/ORGANIZATION 时的根组织

    @property
    def fingerprint(self) -> str:
        return f"hr02:{self.tenant_id}:{self.scope_type}:{self.org_id or ''}"


def resolve_scope(tenant_id, scope_type="SCHOOL", org_id=None, *, user=None) -> Hr02Scope:
    """从请求参数解析 HR02 scope。服务端重新验证，不信任前端。"""
    if not tenant_id:
        raise HrContextError("HR02_TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    valid = {"SCHOOL", "ORG_SUBTREE", "ORGANIZATION", "ASSIGNED_ORGS", "READ_ONLY_SCHOOL"}
    if scope_type not in valid:
        raise HrContextError("HR02_SCOPE_DENIED", f"非法数据范围: {scope_type}")
    # V1：默认 SCHOOL 范围；ORG_SUBTREE 校验由具体 selector 完成
    return Hr02Scope(scope_type=scope_type, tenant_id=tenant_id, org_id=org_id)
