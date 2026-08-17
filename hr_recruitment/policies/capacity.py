"""
hr_recruitment/policies/capacity.py

招聘岗位额度/预占容量规则（总册 1.2/9.6/25.2/HR02 50.1）。

HR02 依赖硬门（总册 1.2）：
- S4 前必须确认 HR02 提供 HrOrganization/HrPostCatalog/HrPosition/HrPositionReservation 或等价接口；
- 未就绪时招聘岗位额度一律使用 LEGACY_CURRENT_SNAPSHOT 降级（显式 UNAVAILABLE），
  不得固化为权威外键。

S1 提供容量查询接口契约 + LEGACY_CURRENT_SNAPSHOT 占位实现。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositionCapacitySnapshot:
    """
    岗位额度快照（数据新鲜度合同，总册 18）。

    status: OK / PARTIAL / STALE / UNAVAILABLE / ERROR
    mode: HR02_AUTHORITY / LEGACY_CURRENT_SNAPSHOT
    """

    position_id: Optional[int]
    position_pool_id: Optional[int]
    post_catalog_id: Optional[int]
    authorized_count: int
    reserved_count: int
    available_count: int
    status: str = "OK"
    mode: str = "LEGACY_CURRENT_SNAPSHOT"
    source_updated_at: Optional[str] = None
    calculated_at: str = ""
    max_stale_seconds: int = 300
    hard_expire_seconds: int = 3600
    meta: dict = field(default_factory=dict)


class CapacityProviderError(Exception):
    """容量查询失败。"""


class CapacityProvider:
    """
    HR02 容量 Provider 接口（S1 契约；S4 接 hr_structure 后替换实现）。

    V1（LEGACY_CURRENT_SNAPSHOT）：返回 UNAVAILABLE 或显式快照，
    禁止臆造可用额度。正式录用动作绝不依赖缓存。
    """

    def query_capacity(
        self,
        *,
        tenant_id: int,
        organization_id: int,
        post_catalog_id: Optional[int] = None,
        position_id: Optional[int] = None,
        position_pool_id: Optional[int] = None,
        force_refresh: bool = False,
    ) -> PositionCapacitySnapshot:
        """查询岗位可用额度。HR02 未就绪时返回 UNAVAILABLE 快照。"""
        if not (position_id or position_pool_id):
            # 无具体岗位引用：无法给出权威额度，必须显式 UNAVAILABLE
            return PositionCapacitySnapshot(
                position_id=None,
                position_pool_id=None,
                post_catalog_id=post_catalog_id,
                authorized_count=0,
                reserved_count=0,
                available_count=0,
                status="UNAVAILABLE",
                mode="LEGACY_CURRENT_SNAPSHOT",
                meta={
                    "reason": "HR02_POSITION_REFERENCE_REQUIRED",
                    "hint": "S4 确认 HR02 HrPosition/HrPositionReservation 接口后启用权威预占",
                },
            )
        raise CapacityProviderError(
            "HR02 capacity provider not wired: S4 依赖硬门未达成"
        )


def require_capacity_for_reservation(snapshot: PositionCapacitySnapshot, reserve_count: int) -> None:
    """
    预占前容量校验（总册 25.2 事务重检的一部分）。

    正式录用/预占动作绝不能依赖缓存；此检查须在事务内配合行锁/唯一约束执行。
    """
    from hr_recruitment.api.exceptions import PositionCapacityConflictError

    if snapshot.status in ("UNAVAILABLE", "ERROR"):
        raise PositionCapacityConflictError(
            "岗位额度不可用（HR02 依赖未就绪或数据陈旧），禁止进行预占"
        )
    if snapshot.status == "STALE":
        raise PositionCapacityConflictError(
            "岗位额度快照已过期，请刷新后重试"
        )
    if snapshot.available_count < reserve_count:
        raise PositionCapacityConflictError(
            f"岗位可用额度不足: 可用 {snapshot.available_count}, 需要 {reserve_count}"
        )
