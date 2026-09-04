"""
hr_structure/scope.py

HR02 数据范围（总册 6.3）：
- SCHOOL / ORG_SUBTREE / ORGANIZATION / ASSIGNED_ORGS / READ_ONLY_SCHOOL
- 所有 selector 第一条件 tenant；禁止裸 `HrOrganization.objects.get(pk=id)`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db.models import Q

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
    if scope_type in {"ORG_SUBTREE", "ORGANIZATION"}:
        try:
            org_id = int(org_id)
            if org_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise HrContextError("HR02_SCOPE_DENIED", "机构范围缺少有效机构")
    return Hr02Scope(scope_type=scope_type, tenant_id=int(tenant_id), org_id=org_id)


def organization_ids_for_scope(scope: Hr02Scope, as_of) -> Optional[set[int]]:
    """Return allowed organization ids; ``None`` means the whole school.

    ``ASSIGNED_ORGS`` must be populated by a future server-side grant provider.
    Until then it deliberately resolves to an empty set instead of widening to
    school scope.
    """
    if scope.scope_type in {"SCHOOL", "READ_ONLY_SCHOOL"}:
        return None
    if scope.scope_type == "ASSIGNED_ORGS":
        return set()

    from hr_structure.models import HrOrganizationVersion
    from hr_structure.selectors.effective import FORMAL_STATUSES

    effective = HrOrganizationVersion.objects.filter(
        tenant_id=scope.tenant_id,
        organization_id=scope.org_id,
        status__in=FORMAL_STATUSES,
        validity_from__lte=as_of,
    ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
    if not effective.exists():
        return set()
    allowed = {int(scope.org_id)}
    if scope.scope_type == "ORGANIZATION":
        return allowed

    frontier = allowed
    while frontier:
        children = set(
            HrOrganizationVersion.objects.filter(
                tenant_id=scope.tenant_id,
                parent_organization_id__in=frontier,
                status__in=FORMAL_STATUSES,
                validity_from__lte=as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
            .values_list("organization_id", flat=True)
        ) - allowed
        allowed.update(children)
        frontier = children
    return allowed
