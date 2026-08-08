"""
hr_recruitment/integrations/hr02.py

HR04 → HR02 岗位预占集成（唯一接入点）。

HR02 已暴露（台账 §1/§2 确认）：
  PositionService.reserve/commit/release（hr_structure/services/position.py）
  - reserve: source_domain/source_business_type/source_business_id + idempotency_key，
    事务锁 select_for_update，HELD 状态，幂等重试命中
  - commit: HELD→COMMITTED
  - release: HELD→RELEASED

HR04 约定：
  source_domain = "hr04"
  source_business_type = "recruitment_position"
  source_business_id = <HrRecruitmentPosition.id>

错误码对齐：HR02_POSITION_NOT_AVAILABLE / HR02_POSITION_NOT_FOUND → PositionCapacityConflictError。
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from hr_recruitment.api.exceptions import PositionCapacityConflictError
from hr_recruitment.policies.capacity import (
    CapacityProvider,
    PositionCapacitySnapshot,
)

SOURCE_DOMAIN = "hr04"
SOURCE_BUSINESS_TYPE = "recruitment_position"


class Hr02ReservationError(Exception):
    """HR02 预占失败（映射为容量冲突/不可用）。"""


class Hr02ReservationProvider:
    """
    HR02 岗位预占 Provider。

    用法（S4 起）：
      provider = Hr02ReservationProvider(tenant_id=..., actor=...)
      reservation = provider.reserve(
          position_id=..., position_pool_id=..., count=2, idempotency_key=...
      )
      provider.commit(reservation_id=...)
      provider.release(reservation_id=...)
    """

    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    def _service(self):
        from hr_structure.scope import Hr02Scope
        from hr_structure.services.position import PositionService

        scope = Hr02Scope(scope_type="SCHOOL", tenant_id=self.tenant_id)
        return PositionService(scope=scope, actor=self.actor)

    def reserve(
        self,
        *,
        position_id=None,
        position_pool_id=None,
        count=1,
        fte=1.00,
        idempotency_key: str,
        expires_at=None,
    ):
        if not (position_id or position_pool_id):
            raise PositionCapacityConflictError(
                "岗位预占需要 position_id 或 position_pool_id"
            )
        service = self._service()
        try:
            reservation = service.reserve(
                source_domain=SOURCE_DOMAIN,
                source_business_type=SOURCE_BUSINESS_TYPE,
                source_business_id=str(position_id or position_pool_id),
                position_id=position_id,
                position_pool_id=position_pool_id,
                count=count,
                fte=fte,
                idempotency_key=idempotency_key,
                expires_at=expires_at or (timezone.now() + timedelta(days=7)),
            )
        except Exception as exc:  # PositionServiceError
            code = getattr(exc, "code", "HR02_RESERVATION_FAILED")
            if code in ("HR02_POSITION_NOT_AVAILABLE", "HR02_POSITION_NOT_FOUND"):
                raise PositionCapacityConflictError(str(exc)) from exc
            raise
        return {
            "reservation_id": str(reservation.id),
            "reservation_no": reservation.reservation_no,
            "status": reservation.status,
        }

    def commit(self, reservation_id: str):
        service = self._service()
        try:
            r = service.commit(int(reservation_id))
        except Exception as exc:
            code = getattr(exc, "code", "HR02_COMMIT_FAILED")
            if code in ("HR02_POSITION_NOT_AVAILABLE", "HR02_POSITION_NOT_FOUND"):
                raise PositionCapacityConflictError(str(exc)) from exc
            raise
        return {"reservation_id": str(r.id), "status": r.status}

    def release(self, reservation_id: str):
        service = self._service()
        try:
            r = service.release(int(reservation_id))
        except Exception as exc:
            code = getattr(exc, "code", "HR02_RELEASE_FAILED")
            if code in ("HR02_POSITION_NOT_AVAILABLE", "HR02_POSITION_NOT_FOUND"):
                raise PositionCapacityConflictError(str(exc)) from exc
            raise
        return {"reservation_id": str(r.id), "status": r.status}


class Hr02CapacityProvider(CapacityProvider):
    """
    HR02 容量 Provider（query_capacity 实现，替换 S1 的占位）。

    读取 HR02 可用额度：max_incumbents - HELD reservations（position 维度）。
    HR02 未返回权威数据时显式 UNAVAILABLE，绝不返回 0。
    """

    def __init__(self, *, tenant_id: int, as_of=None):
        self.tenant_id = tenant_id
        self.as_of = as_of

    def query_capacity(
        self,
        *,
        tenant_id: int,
        organization_id: int,
        post_catalog_id=None,
        position_id=None,
        position_pool_id=None,
        force_refresh=False,
    ) -> PositionCapacitySnapshot:
        if not (position_id or position_pool_id):
            return PositionCapacitySnapshot(
                position_id=None,
                position_pool_id=None,
                post_catalog_id=post_catalog_id,
                authorized_count=0,
                reserved_count=0,
                available_count=0,
                status="UNAVAILABLE",
                mode="HR02_AUTHORITY",
                meta={"reason": "HR02_POSITION_REFERENCE_REQUIRED"},
            )
        try:
            from django.db.models import Sum
            from hr_structure.models import HrPosition, HrPositionPool, HrPositionReservation

            if position_id:
                pos = HrPosition.objects.filter(
                    tenant_id=tenant_id, id=position_id, lifecycle_status="ACTIVE"
                ).first()
                if pos is None:
                    return PositionCapacitySnapshot(
                        position_id=position_id,
                        position_pool_id=None,
                        post_catalog_id=post_catalog_id,
                        authorized_count=0,
                        reserved_count=0,
                        available_count=0,
                        status="UNAVAILABLE",
                        mode="HR02_AUTHORITY",
                        meta={"reason": "HR02_POSITION_NOT_AVAILABLE"},
                    )
                held = (
                    HrPositionReservation.objects.filter(position_id=pos, status="HELD").aggregate(
                        total=Sum("reserved_count")
                    )["total"]
                    or 0
                )
                available = max(pos.max_incumbents - held, 0)
                return PositionCapacitySnapshot(
                    position_id=position_id,
                    position_pool_id=None,
                    post_catalog_id=post_catalog_id,
                    authorized_count=pos.max_incumbents,
                    reserved_count=held,
                    available_count=available,
                    status="OK",
                    mode="HR02_AUTHORITY",
                    calculated_at=timezone.now().isoformat(),
                )
            if position_pool_id:
                pool = HrPositionPool.objects.filter(
                    tenant_id=tenant_id, id=position_pool_id, status="ACTIVE"
                ).first()
                if pool is None:
                    return PositionCapacitySnapshot(
                        position_id=None,
                        position_pool_id=position_pool_id,
                        post_catalog_id=post_catalog_id,
                        authorized_count=0,
                        reserved_count=0,
                        available_count=0,
                        status="UNAVAILABLE",
                        mode="HR02_AUTHORITY",
                        meta={"reason": "HR02_POSITION_NOT_AVAILABLE"},
                    )
                held = (
                    HrPositionReservation.objects.filter(position_pool_id=pool, status="HELD").aggregate(
                        total=Sum("reserved_count")
                    )["total"]
                    or 0
                )
                available = max(pool.authorized_count - held, 0)
                return PositionCapacitySnapshot(
                    position_id=None,
                    position_pool_id=position_pool_id,
                    post_catalog_id=post_catalog_id,
                    authorized_count=pool.authorized_count,
                    reserved_count=held,
                    available_count=available,
                    status="OK",
                    mode="HR02_AUTHORITY",
                    calculated_at=timezone.now().isoformat(),
                )
        except Exception as exc:  # noqa: BLE001
            return PositionCapacitySnapshot(
                position_id=position_id,
                position_pool_id=position_pool_id,
                post_catalog_id=post_catalog_id,
                authorized_count=0,
                reserved_count=0,
                available_count=0,
                status="ERROR",
                mode="HR02_AUTHORITY",
                meta={"reason": str(exc)[:200]},
            )
        return PositionCapacitySnapshot(
            position_id=position_id,
            position_pool_id=position_pool_id,
            post_catalog_id=post_catalog_id,
            authorized_count=0,
            reserved_count=0,
            available_count=0,
            status="UNAVAILABLE",
            mode="HR02_AUTHORITY",
            meta={"reason": "HR02_CAPACITY_UNAVAILABLE"},
        )
