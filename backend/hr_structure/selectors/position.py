"""
hr_structure/selectors/position.py

PositionSelector —— 岗位台账查询（总册 13 节）。

核心：
- occupancy 由 HR03 assignment 派生（INV-09）；HR02 不存 occupied 字段。
- HARD control 的 availability 必须扣除有效 HELD reservation（50.1）。
- 空岗/已占/冻结/超编等状态由权威数据计算，不在前端拼。
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from django.db.models import Q, Sum
from django.utils import timezone

from hr_structure.models import HrPosition, HrPositionPool, HrPositionReservation
from hr_structure.scope import Hr02Scope, organization_ids_for_scope


class PositionSelector:
    def __init__(
        self,
        scope: Hr02Scope,
        as_of: Optional[date] = None,
        occupancy_service=None,
    ):
        self.scope = scope
        self.as_of = as_of or timezone.localdate()
        if occupancy_service is None:
            from hr_staff.services.effective_dated_query_service import (
                EffectiveDatedQueryService,
            )

            occupancy_service = EffectiveDatedQueryService(scope.tenant_id)
        self.occupancy_service = occupancy_service

    def _base(self):
        qs = HrPosition.objects.filter(
            tenant_id=self.scope.tenant_id,
            validity_from__lte=self.as_of,
        ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=self.as_of))
        allowed = organization_ids_for_scope(self.scope, self.as_of)
        return qs if allowed is None else qs.filter(organization_id__in=allowed)

    def _occupancy_counts(self, position_ids) -> dict:
        return self.occupancy_service.position_occupancy_by_position_as_of(
            position_ids,
            self.as_of,
        )

    def _reservation_reference(self):
        """把日粒度 as_of 映射到预占的时刻口径。"""
        now = timezone.now()
        if self.as_of == timezone.localdate(now):
            return now
        reference = datetime.combine(self.as_of, time.min)
        if timezone.is_aware(now):
            return timezone.make_aware(reference, timezone.get_current_timezone())
        return reference

    def _reservation_counts(self, position_ids) -> dict:
        position_ids = tuple(position_ids)
        if not position_ids:
            return {}
        reference = self._reservation_reference()
        rows = (
            HrPositionReservation.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id__in=position_ids,
                status=HrPositionReservation.Status.HELD,
                reserved_at__lte=reference,
                expires_at__gt=reference,
            )
            .values("position_id")
            .annotate(reserved_count=Sum("reserved_count"))
        )
        return {row["position_id"]: row["reserved_count"] or 0 for row in rows}

    def list_positions(
        self, organization_id=None, lifecycle_status=None, page=1, page_size=20
    ):
        """DB 分页查询（禁止全量加载后前端分页）。"""
        qs = self._base()
        if organization_id:
            qs = qs.filter(organization_id_id=organization_id)
        if lifecycle_status:
            qs = qs.filter(lifecycle_status=lifecycle_status)
        total = qs.count()
        start = (page - 1) * page_size
        items = list(
            qs.select_related(
                "organization_id", "post_catalog_version_id", "post_grade_id"
            )
            .order_by("position_code")[start : start + page_size]
        )
        position_ids = [p.id for p in items]
        occupancy = self._occupancy_counts(position_ids)
        reservations = self._reservation_counts(position_ids)
        return {
            "total": total,
            "items": [
                self._dto(
                    p,
                    occupied_count=occupancy.get(p.id, 0),
                    reserved_count=reservations.get(p.id, 0),
                )
                for p in items
            ],
        }

    def get_position(self, position_id) -> Optional[dict]:
        p = (
            self._base()
            .select_related(
                "organization_id", "post_catalog_version_id", "post_grade_id"
            )
            .filter(id=position_id)
            .first()
        )
        return self._dto(p) if p else None

    def _dto(
        self,
        p: HrPosition,
        *,
        occupied_count: Optional[int] = None,
        reserved_count: Optional[int] = None,
    ) -> dict:
        """岗位 DTO：占用取 HR03，预占单列，两者共同扣减可用量。"""
        if occupied_count is None:
            occupied_count = self._occupancy_counts([p.id]).get(p.id, 0)
        if reserved_count is None:
            reserved_count = self._reservation_counts([p.id]).get(p.id, 0)
        occupancy = occupied_count
        if occupancy == 0:
            occ_status = "VACANT"
        elif occupancy < p.max_incumbents:
            occ_status = "PARTIALLY_FILLED"
        elif occupancy == p.max_incumbents:
            occ_status = "FILLED"
        else:
            occ_status = "OVERFILLED"
        dto = {
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
            "reservedCount": reserved_count,
            "availableCount": max(0, p.max_incumbents - occupancy - reserved_count),
            "dataBasis": "AUTHORITATIVE_EFFECTIVE_FACT",
        }
        from hr_structure.display_labels import (
            POSITION_LIFECYCLE_STATUS,
            POSITION_OCCUPANCY_STATUS,
            label_of,
        )

        dto["lifecycleStatusLabel"] = label_of(
            POSITION_LIFECYCLE_STATUS, p.lifecycle_status
        )
        dto["occupancyStatusLabel"] = label_of(
            POSITION_OCCUPANCY_STATUS, occ_status
        )
        return dto

    def availability(
        self, position_id=None, post_catalog_version_id=None, organization_id=None
    ) -> dict:
        """可用性（HR04 招聘/HR06 调动调用契约）。HARD 扣减 HELD reservation。"""
        # 单个岗位可用性
        if position_id:
            p = self._base().filter(id=position_id).first()
            if p is None:
                return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}
            if p.lifecycle_status != HrPosition.LifecycleStatus.ACTIVE:
                return {"available": False, "reason": f"岗位状态 {p.lifecycle_status}"}
            held = self._reservation_counts([p.id]).get(p.id, 0)
            occupied = self._occupancy_counts([p.id]).get(p.id, 0)
            free = max(0, p.max_incumbents - occupied - held)
            return {
                "available": free > 0,
                "free": free,
                "occupied": occupied,
                "reserved": held,
                "dataBasis": "AUTHORITATIVE_EFFECTIVE_FACT",
            }
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
            allowed = organization_ids_for_scope(self.scope, self.as_of)
            if allowed is not None and int(organization_id) not in allowed:
                pool = None
            if pool is None:
                return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}
            reference = self._reservation_reference()
            held = (
                HrPositionReservation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    position_pool_id=pool,
                    status=HrPositionReservation.Status.HELD,
                    reserved_at__lte=reference,
                    expires_at__gt=reference,
                )
                .aggregate(t=Sum("reserved_count"))["t"]
                or 0
            )
            free = max(0, pool.authorized_count - held)
            return {"available": free > 0, "free": free, "reserved": held}
        return {"available": False, "reason": "HR02_POSITION_NOT_FOUND"}

    def control_summary(self) -> dict:
        """岗位容量汇总；冻结容量单列，不参与可用量。"""
        positions = list(
            self._base()
            .filter(
                lifecycle_status__in=(
                    HrPosition.LifecycleStatus.ACTIVE,
                    HrPosition.LifecycleStatus.FROZEN,
                )
            )
            .only("id", "max_incumbents", "lifecycle_status")
        )
        active_positions = [
            p
            for p in positions
            if p.lifecycle_status == HrPosition.LifecycleStatus.ACTIVE
        ]
        active_ids = [p.id for p in active_positions]
        occupancy = self._occupancy_counts(active_ids)
        reservations = self._reservation_counts(active_ids)
        authorized = sum(p.max_incumbents for p in active_positions)
        frozen = sum(
            p.max_incumbents
            for p in positions
            if p.lifecycle_status == HrPosition.LifecycleStatus.FROZEN
        )
        occupied = sum(occupancy.values())
        reserved = sum(reservations.values())
        available = sum(
            max(
                0,
                p.max_incumbents
                - occupancy.get(p.id, 0)
                - reservations.get(p.id, 0),
            )
            for p in active_positions
        )
        vacant = sum(
            max(0, p.max_incumbents - occupancy.get(p.id, 0))
            for p in active_positions
        )
        over = sum(
            max(0, occupancy.get(p.id, 0) - p.max_incumbents)
            for p in active_positions
        )
        return {
            "authorized": authorized,
            "occupied": occupied,
            "reserved": reserved,
            "available": available,
            "vacant": vacant,
            "frozen": frozen,
            "over": over,
            "dataBasis": "AUTHORITATIVE_EFFECTIVE_FACT",
        }
