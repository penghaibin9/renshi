"""
hr_structure/selectors/effective.py

EffectiveDatedQueryService —— 统一 as-of 查询（总册 8.4 / 19.2）。

- 历史 as-of 必须 DB 查询有效区间，禁止 Python load all → filter by date。
- 只有 status IN (APPROVED, EFFECTIVE, SUPERSEDED) 参与正式 as-of 解析（DRAFT/REJECTED/CANCELLED 不参与）。
- 同一 organization_id 正式版本区间不得重叠（INV-04）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q

from hr_structure.models import HrOrganizationVersion

FORMAL_STATUSES = ("APPROVED", "EFFECTIVE", "SUPERSEDED")


def org_version_as_of(organization_id, as_of: date) -> Optional[HrOrganizationVersion]:
    """解析某组织在 as_of 日期的有效版本。"""
    return (
        HrOrganizationVersion.objects.filter(
            organization_id=organization_id,
            status__in=FORMAL_STATUSES,
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .order_by("-version_no")
        .first()
    )


def post_catalog_version_as_of(catalog_id, as_of: date) -> Optional["HrPostCatalogVersion"]:
    """解析某岗位目录在 as_of 日期的有效版本。"""
    from hr_structure.models import HrPostCatalogVersion

    return (
        HrPostCatalogVersion.objects.filter(
            catalog_id=catalog_id,
            status__in=("ACTIVE",),
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .order_by("-version_no")
        .first()
    )


def position_as_of(position_id, as_of: date) -> Optional["HrPosition"]:
    """岗位在 as_of 日期的有效状态（lifecycle + validity）。"""
    from hr_structure.models import HrPosition

    return (
        HrPosition.objects.filter(
            id=position_id,
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .first()
    )


def position_pool_as_of(pool_id, as_of: date) -> Optional["HrPositionPool"]:
    """岗位池在 as_of 日期的有效状态。"""
    from hr_structure.models import HrPositionPool

    return (
        HrPositionPool.objects.filter(
            id=pool_id,
            status="ACTIVE",
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .first()
    )


def children_as_of(tenant_id, parent_org_id, as_of: date, dimension=None):
    """某组织在 as_of 的直接下级（同 dimension 主树）。"""
    qs = HrOrganizationVersion.objects.filter(
        tenant_id=tenant_id,
        status__in=FORMAL_STATUSES,
        parent_organization_id=parent_org_id,
        validity_from__lte=as_of,
    ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
    if dimension:
        qs = qs.filter(organization_id__org_dimension=dimension)
    return qs.select_related("organization_id", "parent_organization_id").order_by(
        "sort_order", "name"
    )


def build_tree_as_of(tenant_id, root_org_id, as_of: date, dimension=None, depth_limit=10):
    """构建 as_of 组织树（懒加载友好：返回节点 + has_children）。"""
    nodes = []
    root_version = org_version_as_of(root_org_id, as_of)
    if root_version is None:
        return []
    stack = [(root_version, 0)]
    while stack:
        version, depth = stack.pop()
        children = list(children_as_of(tenant_id, version.organization_id_id, as_of, dimension))
        nodes.append(
            {
                "id": version.organization_id_id,
                "stable_code": version.organization_id.stable_code,
                "name": version.name,
                "org_type": version.org_type,
                "depth": depth,
                "has_children": bool(children),
                "validity_from": version.validity_from.isoformat(),
                "validity_to": version.validity_to.isoformat() if version.validity_to else None,
            }
        )
        if depth + 1 < depth_limit:
            for child in reversed(children):
                stack.append((child, depth + 1))
    return nodes
