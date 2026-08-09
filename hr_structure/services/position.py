"""
hr_structure/services/position.py

PositionService —— 岗位供给与预占（总册 13 节 + 50.1）。

核心：
- position/pool 生命周期管理；
- HrPositionReservation 预占（事务锁防并发超卖 INV-14）；
- occupancy 由 HR03 assignment 派生，HR02 不手填（INV-09）。
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from hr_structure.models import HrPosition, HrPositionPool, HrPositionReservation
from hr_structure.scope import Hr02Scope


class PositionServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.http_status = http_status
        super().__init__(message)


class PositionService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    # ---- Position 生命周期 ----

    @transaction.atomic
    def create_position(
        self,
        *,
        position_code,
        organization_id,
        post_catalog_version_id,
        planned_fte=1.00,
        validity_from=None,
        **kwargs,
    ) -> HrPosition:
        position = HrPosition.objects.create(
            tenant_id=self.scope.tenant_id,
            position_code=position_code,
            organization_id_id=organization_id,
            post_catalog_version_id_id=post_catalog_version_id,
            planned_fte=planned_fte,
            validity_from=validity_from or date.today(),
            lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
            **kwargs,
        )
        return position

    @transaction.atomic
    def freeze(self, position_id, reason=""):
        with transaction.atomic():
            pos = (
                HrPosition.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=position_id)
                .first()
            )
            if pos is None:
                raise PositionServiceError("HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404)
            if pos.lifecycle_status == HrPosition.LifecycleStatus.CLOSED:
                raise PositionServiceError("HR02_POSITION_FROZEN", "已关闭岗位不能冻结")
            pos.lifecycle_status = HrPosition.LifecycleStatus.FROZEN
            pos.freeze_reason = reason
            pos.version += 1
            pos.save(update_fields=["lifecycle_status", "freeze_reason", "version"])
            return pos

    @transaction.atomic
    def close(self, position_id, reason=""):
        with transaction.atomic():
            pos = (
                HrPosition.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=position_id)
                .first()
            )
            if pos is None:
                raise PositionServiceError("HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404)
            pos.lifecycle_status = HrPosition.LifecycleStatus.CLOSED
            pos.close_reason = reason
            pos.version += 1
            pos.save(update_fields=["lifecycle_status", "close_reason", "version"])
            return pos

    # ---- Reservation（预占，防并发超卖）----

    @transaction.atomic
    def reserve(
        self,
        *,
        source_domain,
        source_business_type,
        source_business_id,
        position_id=None,
        position_pool_id=None,
        count=1,
        fte=1.00,
        idempotency_key,
        expires_at=None,
    ) -> HrPositionReservation:
        """创建预占（HARD control 下必须扣除 HELD reservation 计算可用性）。"""
        existing = HrPositionReservation.objects.filter(
            tenant_id=self.scope.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing  # 幂等重试

        # 先清理过期预占，避免过期 HELD 继续占额（总册 50.1）
        self.expire_overdue()

        if position_id:
            pos = (
                HrPosition.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=position_id, lifecycle_status="ACTIVE")
                .first()
            )
            if pos is None:
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", "岗位不存在或未激活")
            # 计算已占用（HELD reservation 也算占用）
            held = HrPositionReservation.objects.filter(
                position_id=pos, status="HELD"
            ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("reserved_count"))["total"] or 0
            if held + count > pos.max_incumbents:
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", "岗位可用额度不足")

        if position_pool_id:
            pool = (
                HrPositionPool.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=position_pool_id, status="ACTIVE")
                .first()
            )
            if pool is None:
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", "岗位池不存在或未激活")
            held = HrPositionReservation.objects.filter(
                position_pool_id=pool, status="HELD"
            ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("reserved_count"))["total"] or 0
            if held + count > pool.authorized_count:
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", "岗位池可用额度不足")

        reservation = HrPositionReservation.objects.create(
            tenant_id=self.scope.tenant_id,
            reservation_no=f"RESV-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            position_id_id=position_id,
            position_pool_id_id=position_pool_id,
            source_domain=source_domain,
            source_business_type=source_business_type,
            source_business_id=source_business_id,
            reserved_count=count,
            reserved_fte=fte,
            status=HrPositionReservation.Status.HELD,
            expires_at=expires_at or (timezone.now() + __import__("datetime", fromlist=["timedelta"]).timedelta(days=7)),
            idempotency_key=idempotency_key,
        )
        return reservation

    @transaction.atomic
    def commit(self, reservation_id):
        with transaction.atomic():
            r = (
                HrPositionReservation.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=reservation_id)
                .first()
            )
            if r is None:
                raise PositionServiceError("HR02_POSITION_NOT_FOUND", "预占不存在", http_status=404)
            if r.status not in (HrPositionReservation.Status.HELD, HrPositionReservation.Status.COMMITTED):
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", f"预占状态 {r.status} 不可提交")
            r.status = HrPositionReservation.Status.COMMITTED
            r.committed_at = timezone.now()
            r.save(update_fields=["status", "committed_at"])
            return r

    @transaction.atomic
    def release(self, reservation_id):
        with transaction.atomic():
            r = (
                HrPositionReservation.objects.select_for_update()
                .filter(tenant_id=self.scope.tenant_id, id=reservation_id)
                .first()
            )
            if r is None:
                raise PositionServiceError("HR02_POSITION_NOT_FOUND", "预占不存在", http_status=404)
            if r.status != HrPositionReservation.Status.HELD:
                raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", f"预占状态 {r.status} 不可释放")
            r.status = HrPositionReservation.Status.RELEASED
            r.released_at = timezone.now()
            r.save(update_fields=["status", "released_at"])
            return r

    @transaction.atomic
    def expire_overdue(self, *, as_of=None) -> int:
        """把已过期（expires_at < now）的 HELD 预占置为 EXPIRED（总册 50.1）。

        返回处理条数。后台任务/管理命令调用。
        """
        from django.utils import timezone as _tz

        now = as_of or _tz.now()
        qs = HrPositionReservation.objects.filter(
            tenant_id=self.scope.tenant_id,
            status=HrPositionReservation.Status.HELD,
            expires_at__lt=now,
        ).select_for_update()
        count = qs.update(status=HrPositionReservation.Status.EXPIRED)
        return count
