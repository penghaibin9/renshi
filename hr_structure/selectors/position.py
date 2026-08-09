"""
hr_structure/selectors/position.py

PositionSelector —— 岗位台账查询（总册 13 节）。

核心：
- occupancy 由 HR03 assignment 派生（INV-09）；HR02 不存 occupied 字段。
- HARD control 的 availability 必须扣除有效 HELD reservation（50.1）。
- 空岗/已占/冻结/超编等状态由权威数据计算，不在前端拼。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q, Sum

from hr_structure.models import HrPosition, HrPositionPool, HrPositionReservation
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.effective import position_as_of, position_pool_as_of


class PositionSelector:
    def __init__(self, scope: Hr02Scope, as_of: Optional[date] = None):
        self.scope = scope
        self.as_of = as_of or date.today()

    def _base(self):
        return HrPosition.objects.filter(tenant_id=self.scope.tenant_id)

    def list_positions(self, organization_id=None, lifecycle_status=None, page=1, page_size=20):
        """DB 分页查询（禁止全量加载后前端分页）。"""
        qs = self._base()
        if organization_id:
            qs = qs.filter(organization_id_id=organization_id)
        if lifecycle_status:
            qs = qs.filter(lifecycle_status=lifecycle_status)
        total = qs.count()
        start = (page - 1) * page_size
        items = (
            qs.select_related("organization_id", "post_catalog_version_id", "post_grade_id")
            .order_by("position_code")[start : start + page_size]
        )
        return {"total": total, "items": [self._dto(p) for p in items]}

    def get_position(self, position_id) -> Optional[dict]:
        p = self._base().filter(id=position_id).first()
        return self._dto(p) if p else None

    def _dto(self, p: HrPosition) -> dict:
        """DTO：含派生 occupancy 状态（VACANT/FILLED/OVERFILLED 由 reservation+assignment 计算）。"""
        held = (
            HrPositionReservation.objects.filter(
                position_id=p, status="HELD"
            ).aggregate(t=Sum("reserved_count"))["t"]
            or 0
        )
        # occupancy: HR03 assignment 派生（V1 未接入 HR03 → LEGACY_CURRENT_SNAPSHOT）
        # 此处预留 occupancy provider 契约；当前用 reservation 作占位
        occupancy = held
        if occupancy == 0:
            occ_status = "VACANT"
        elif occupancy < p.max_incumbents:
            occ_status = "PARTIALLY_FILLED"
        elif occupancy == p.max_incumbents:
            occ_status = "FILLED"
        else:
            occ_status = "OVERFILLED"
        return {
            "id": p.id,
            "positionCode": p.position_code,
            "organizationId": p.organization_id_id,
            "organizationName": getattr(p.organization_id, "stable_code", ""),
            "postCatalog": getattr(p.post_catalog_version_id, "name", ""),
            "postGrade": getattr(p.post_grade_id, "name", "") if p.post_grade_id else "",
            "plannedFte": str(p.planned_fte),
            "maxIncumbents": p.max_incumbents,
            "lifecycleStatus": p.lifecycle_status,
            "occupancyStatus": occ_status,
            "occupiedCount": occupancy,
            "dataBasis": "LEGACY_CURRENT_SNAPSHOT",
        }

    def availability(self, position_id=None, post_catalog_version_id=None, organization_id=None) -> dict:
        """可用性（HR04 招聘/HR06 调动调用契约）。HARD 扣减 HELD reservation。"""
        # 单个岗位可用性
        if position_id:
            p = self._base().filter(id=position_id).first()
            if p is None:
                return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}
            if p.lifecycle_status != HrPosition.LifecycleStatus.ACTIVE:
                return {"available": False, "reason": f"岗位状态 {p.lifecycle_status}"}
            from django.utils import timezone as _tz

            held = (
                HrPositionReservation.objects.filter(
                    position_id=p, status="HELD", expires_at__gt=_tz.now()
                )
                .aggregate(t=Sum("reserved_count"))["t"]
                or 0
            )
            free = p.max_incumbents - held
            return {"available": free > 0, "free": free, "reserved": held}
        # 岗位池可用性
        if post_catalog_version_id and organization_id:
            pool = (
                HrPositionPool.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    organization_id_id=organization_id,
                    post_catalog_version_id_id=post_catalog_version_id,
                    status="ACTIVE",
                ).first()
            )
            if pool is None:
                return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}
            from django.utils import timezone as _tz

            held = (
                HrPositionReservation.objects.filter(
                    position_pool_id=pool, status="HELD", expires_at__gt=_tz.now()
                )
                .aggregate(t=Sum("reserved_count"))["t"]
                or 0
            )
            free = pool.authorized_count - held
            return {"available": free > 0, "free": free, "reserved": held}
        return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}
