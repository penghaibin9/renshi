"""
hr_recruitment/selectors/scope_utils.py

数据范围过滤 helper（总册 §6.2 / §35 跨学院 scope）。

- SCOPE=SCHOOL：无组织过滤；
- SCOPE=COLLEGE/DEPARTMENT：按 scope.org_id 过滤 organization_id（服务端强制，不信任前端）。
"""

from __future__ import annotations

from django.db.models import Q


def org_scope_q(scope, org_field="organization_id") -> Q | None:
    """由 ctx.scope 构造组织过滤 Q（None 表示不限定）。"""
    scope_type = getattr(scope, "scope_type", "SCHOOL")
    org_id = getattr(scope, "org_id", None)
    if scope_type in ("COLLEGE", "DEPARTMENT") and org_id:
        return Q(**{f"{org_field}": org_id})
    return None


def apply_org_scope(qs, scope, org_field="organization_id"):
    """对 queryset 应用组织范围过滤（org_field 支持跨关系路径）。"""
    q = org_scope_q(scope, org_field)
    if q is None:
        return qs
    return qs.filter(q)
