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
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from horilla.hr_event_service import emit_registered_event

from hr_structure.authority_registry import (
    EVENT_POSITION_CREATED,
    EVENT_POSITION_STATUS_CHANGED,
    EVENT_RESERVATION_COMMITTED,
    EVENT_RESERVATION_HELD,
    EVENT_RESERVATION_RELEASED,
)
from hr_structure.models import (
    HrOrganization,
    HrPosition,
    HrPositionPool,
    HrPositionReservation,
    HrPositionVersion,
    HrPostCatalogVersion,
)
from hr_structure.scope import Hr02Scope


class PositionServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class PositionService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    # ---- Position 生命周期 ----

    @staticmethod
    def _bool_value(value):
        if isinstance(value, bool):
            return value
        if value in (1, "1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
            return True
        if value in (0, "0", "false", "FALSE", "False", "no", "NO", "off", "OFF"):
            return False
        raise PositionServiceError("HR02_INVALID_REQUEST", "布尔值格式非法")

    @staticmethod
    def _positive_int_value(value, label):
        try:
            parsed = Decimal(str(value))
            if parsed <= 0 or parsed != parsed.to_integral_value():
                raise InvalidOperation
            return int(parsed)
        except (InvalidOperation, TypeError, ValueError):
            raise PositionServiceError(
                "HR02_POSITION_CAPACITY_INVALID", f"{label}必须是正整数"
            )

    def _validate_create_contract(
        self,
        *,
        position_code,
        organization_id,
        post_catalog_version_id,
        planned_fte,
        max_incumbents,
        validity_from,
    ):
        if not str(position_code or "").strip():
            raise PositionServiceError("HR02_POSITION_CODE_REQUIRED", "岗位编码不能为空")
        if HrPosition.objects.filter(
            tenant_id=self.scope.tenant_id, position_code=str(position_code).strip()
        ).exists():
            raise PositionServiceError("HR02_POSITION_CODE_CONFLICT", "岗位编码已存在")
        org = HrOrganization.objects.filter(
            tenant_id=self.scope.tenant_id,
            id=organization_id,
            identity_status=HrOrganization.IdentityStatus.ACTIVE,
        ).first()
        if org is None:
            raise PositionServiceError(
                "HR02_CROSS_TENANT_REFERENCE", "组织不存在、已停用或跨租户"
            )
        catalog = (
            HrPostCatalogVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                id=post_catalog_version_id,
                status=HrPostCatalogVersion.Status.ACTIVE,
                validity_from__lte=validity_from,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=validity_from))
            .first()
        )
        if catalog is None:
            raise PositionServiceError(
                "HR02_CROSS_TENANT_REFERENCE", "岗位目录版本不存在、未生效或跨租户"
            )
        try:
            if Decimal(str(planned_fte)) <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise PositionServiceError("HR02_POSITION_FTE_INVALID", "计划 FTE 必须大于 0")
        self._positive_int_value(max_incumbents, "最大任职人数")

    def _current_history(self, position, as_of):
        current = (
            HrPositionVersion.objects.select_for_update()
            .filter(
                tenant_id=self.scope.tenant_id,
                position_id=position.id,
                validity_from__lte=as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
            .order_by("-version_no")
            .first()
        )
        if current is None:
            current = HrPositionVersion.objects.create(
                position_id=position,
                tenant_id=self.scope.tenant_id,
                organization_id_id=position.organization_id_id,
                post_catalog_version_id_id=position.post_catalog_version_id_id,
                post_grade_id_id=position.post_grade_id_id,
                position_type=position.position_type,
                planned_fte=position.planned_fte,
                max_incumbents=position.max_incumbents,
                allow_multiple_incumbents=position.allow_multiple_incumbents,
                lifecycle_status=position.lifecycle_status,
                validity_from=position.validity_from,
                validity_to=position.validity_to,
                version_no=position.version,
                change_case_id="LEGACY_BASELINE",
                reason="legacy position baseline",
                created_by=self.actor,
            )
        return current

    def _append_history(self, position, *, as_of, status, reason, **changes):
        current = self._current_history(position, as_of)
        if as_of < current.validity_from:
            raise PositionServiceError(
                "HR02_EFFECTIVE_RANGE_OVERLAP", "状态生效日不得早于岗位版本开始日"
            )
        if HrPositionVersion.objects.filter(
            tenant_id=self.scope.tenant_id,
            position_id=position.id,
            validity_from__gte=as_of,
        ).exclude(id=current.id).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=as_of)
        ).exists():
            raise PositionServiceError(
                "HR02_EFFECTIVE_RANGE_OVERLAP", "岗位已存在同日或未来版本"
            )
        current.validity_to = as_of
        current.save(update_fields=["validity_to"])
        values = {
            "organization_id_id": position.organization_id_id,
            "post_catalog_version_id_id": position.post_catalog_version_id_id,
            "post_grade_id_id": position.post_grade_id_id,
            "position_type": position.position_type,
            "planned_fte": position.planned_fte,
            "max_incumbents": position.max_incumbents,
            "allow_multiple_incumbents": position.allow_multiple_incumbents,
            "lifecycle_status": status,
        }
        values.update(changes)
        return HrPositionVersion.objects.create(
            position_id=position,
            tenant_id=self.scope.tenant_id,
            validity_from=as_of,
            validity_to=position.validity_to,
            version_no=current.version_no + 1,
            reason=reason,
            created_by=self.actor,
            **values,
        )

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
        validity_from = validity_from or timezone.localdate()
        max_incumbents = kwargs.get("max_incumbents", 1)
        position_type = kwargs.get("position_type", HrPosition.PositionType.REGULAR)
        if position_type not in {value for value, _ in HrPosition.PositionType.choices}:
            raise PositionServiceError("HR02_INVALID_REQUEST", "岗位类型非法")
        kwargs["allow_multiple_incumbents"] = self._bool_value(
            kwargs.get("allow_multiple_incumbents", False)
        )
        grade_id = kwargs.get("post_grade_id_id") or kwargs.get("post_grade_id")
        if grade_id:
            from hr_structure.models import HrPostGrade

            if not HrPostGrade.objects.filter(
                id=grade_id, scheme_id__tenant_id=self.scope.tenant_id
            ).exists():
                raise PositionServiceError(
                    "HR02_CROSS_TENANT_REFERENCE", "岗位等级不存在或跨租户"
                )
        self._validate_create_contract(
            position_code=position_code,
            organization_id=organization_id,
            post_catalog_version_id=post_catalog_version_id,
            planned_fte=planned_fte,
            max_incumbents=max_incumbents,
            validity_from=validity_from,
        )
        kwargs["max_incumbents"] = self._positive_int_value(
            max_incumbents, "最大任职人数"
        )
        position = HrPosition.objects.create(
            tenant_id=self.scope.tenant_id,
            position_code=str(position_code).strip(),
            organization_id_id=organization_id,
            post_catalog_version_id_id=post_catalog_version_id,
            planned_fte=planned_fte,
            validity_from=validity_from,
            lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
            **kwargs,
        )
        HrPositionVersion.objects.create(
            position_id=position,
            tenant_id=self.scope.tenant_id,
            organization_id_id=position.organization_id_id,
            post_catalog_version_id_id=position.post_catalog_version_id_id,
            post_grade_id_id=position.post_grade_id_id,
            position_type=position.position_type,
            planned_fte=position.planned_fte,
            max_incumbents=position.max_incumbents,
            allow_multiple_incumbents=position.allow_multiple_incumbents,
            lifecycle_status=position.lifecycle_status,
            validity_from=position.validity_from,
            validity_to=position.validity_to,
            version_no=position.version,
            reason="CREATE_POSITION",
            created_by=self.actor,
        )
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_POSITION_CREATED,
            payload={
                "positionId": str(position.id),
                "positionCode": position.position_code,
                "organizationId": str(position.organization_id_id),
                "effectiveDate": position.validity_from.isoformat(),
            },
        )
        return position

    @transaction.atomic
    def update_position(self, position_id, *, expected_version=None, **changes):
        """立即变更岗位属性；组织迁移和关闭必须走专用动作。"""
        position = HrPosition.objects.select_for_update().filter(
            tenant_id=self.scope.tenant_id, id=position_id
        ).first()
        if position is None:
            raise PositionServiceError(
                "HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404
            )
        if position.lifecycle_status in {
            HrPosition.LifecycleStatus.CLOSED,
            HrPosition.LifecycleStatus.CANCELLED,
        }:
            raise PositionServiceError("HR02_POSITION_NOT_AVAILABLE", "终态岗位不可变更")
        if expected_version is not None and int(expected_version) != position.version:
            raise PositionServiceError(
                "HR02_VERSION_CONFLICT", "岗位已被其他用户更新，请刷新后重试", http_status=409
            )
        if any(key in changes for key in ("organization_id", "organization_id_id")):
            raise PositionServiceError(
                "HR02_REORG_REQUIRED", "岗位迁移必须通过组织变更 case 执行"
            )

        history_changes = {}
        projection_fields = []
        if "post_catalog_version_id" in changes:
            catalog_id = changes["post_catalog_version_id"]
            catalog = (
                HrPostCatalogVersion.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    id=catalog_id,
                    status=HrPostCatalogVersion.Status.ACTIVE,
                    validity_from__lte=timezone.localdate(),
                )
                .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=timezone.localdate()))
                .first()
            )
            if catalog is None:
                raise PositionServiceError(
                    "HR02_CROSS_TENANT_REFERENCE", "岗位目录版本不可用或跨租户"
                )
            history_changes["post_catalog_version_id_id"] = catalog.id
            position.post_catalog_version_id_id = catalog.id
            projection_fields.append("post_catalog_version_id")
        if "post_grade_id" in changes:
            from hr_structure.models import HrPostGrade

            grade_id = changes["post_grade_id"]
            if grade_id and not HrPostGrade.objects.filter(
                id=grade_id, scheme_id__tenant_id=self.scope.tenant_id
            ).exists():
                raise PositionServiceError(
                    "HR02_CROSS_TENANT_REFERENCE", "岗位等级不存在或跨租户"
                )
            history_changes["post_grade_id_id"] = grade_id or None
            position.post_grade_id_id = grade_id or None
            projection_fields.append("post_grade_id")
        if "position_type" in changes:
            value = changes["position_type"]
            if value not in {value for value, _ in HrPosition.PositionType.choices}:
                raise PositionServiceError("HR02_INVALID_REQUEST", "岗位类型非法")
            history_changes["position_type"] = value
            position.position_type = value
            projection_fields.append("position_type")
        if "planned_fte" in changes:
            try:
                value = Decimal(str(changes["planned_fte"]))
                if value <= 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                raise PositionServiceError("HR02_POSITION_FTE_INVALID", "计划 FTE 必须大于 0")
            history_changes["planned_fte"] = value
            position.planned_fte = value
            projection_fields.append("planned_fte")
        if "max_incumbents" in changes:
            value = self._positive_int_value(
                changes["max_incumbents"], "最大任职人数"
            )
            from hr_staff.models import HrStaffAssignment

            occupied = HrStaffAssignment.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id=position.id,
                status="ACTIVE",
                effective_from__lte=timezone.localdate(),
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=timezone.localdate())
            ).count()
            if value < occupied:
                raise PositionServiceError(
                    "HR02_POSITION_CAPACITY_CONFLICT",
                    f"岗位上限 {value} 低于当前在岗人数 {occupied}",
                )
            history_changes["max_incumbents"] = value
            position.max_incumbents = value
            projection_fields.append("max_incumbents")
        if "allow_multiple_incumbents" in changes:
            value = self._bool_value(changes["allow_multiple_incumbents"])
            history_changes["allow_multiple_incumbents"] = value
            position.allow_multiple_incumbents = value
            projection_fields.append("allow_multiple_incumbents")
        if not projection_fields:
            raise PositionServiceError("HR02_INVALID_REQUEST", "未提供可变更的岗位字段")

        self._append_history(
            position,
            as_of=timezone.localdate(),
            status=position.lifecycle_status,
            reason="CHANGE_POSITION",
            **history_changes,
        )
        position.version += 1
        projection_fields.append("version")
        position.save(update_fields=projection_fields)
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_POSITION_STATUS_CHANGED,
            payload={
                "positionId": str(position.id),
                "status": position.lifecycle_status,
                "actionType": "CHANGE_POSITION",
                "version": position.version,
            },
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
                raise PositionServiceError(
                    "HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404
                )
            if pos.lifecycle_status == HrPosition.LifecycleStatus.CLOSED:
                raise PositionServiceError("HR02_POSITION_FROZEN", "已关闭岗位不能冻结")
            if pos.lifecycle_status == HrPosition.LifecycleStatus.FROZEN:
                return pos
            held = HrPositionReservation.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id=pos.id,
                status=HrPositionReservation.Status.HELD,
            ).count()
            if held:
                raise PositionServiceError(
                    "HR02_POSITION_HAS_RESERVATIONS",
                    f"岗位有 {held} 条未处理预占，不能冻结",
                )
            effective_date = timezone.localdate()
            self._append_history(
                pos,
                as_of=effective_date,
                status=HrPosition.LifecycleStatus.FROZEN,
                reason=reason or "FREEZE_POSITION",
            )
            pos.lifecycle_status = HrPosition.LifecycleStatus.FROZEN
            pos.freeze_reason = reason
            pos.version += 1
            pos.save(update_fields=["lifecycle_status", "freeze_reason", "version"])
            emit_registered_event(
                tenant_id=self.scope.tenant_id,
                event_name=EVENT_POSITION_STATUS_CHANGED,
                payload={
                    "positionId": str(pos.id),
                    "status": pos.lifecycle_status,
                    "reason": reason,
                    "version": pos.version,
                },
            )
            return pos

    @transaction.atomic
    def unfreeze(self, position_id, reason=""):
        pos = (
            HrPosition.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=position_id)
            .first()
        )
        if pos is None:
            raise PositionServiceError(
                "HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404
            )
        if pos.lifecycle_status == HrPosition.LifecycleStatus.ACTIVE:
            return pos
        if pos.lifecycle_status != HrPosition.LifecycleStatus.FROZEN:
            raise PositionServiceError(
                "HR02_POSITION_NOT_AVAILABLE", f"当前状态 {pos.lifecycle_status} 不能解冻"
            )
        self._append_history(
            pos,
            as_of=timezone.localdate(),
            status=HrPosition.LifecycleStatus.ACTIVE,
            reason=reason or "UNFREEZE_POSITION",
        )
        pos.lifecycle_status = HrPosition.LifecycleStatus.ACTIVE
        pos.freeze_reason = ""
        pos.version += 1
        pos.save(update_fields=["lifecycle_status", "freeze_reason", "version"])
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_POSITION_STATUS_CHANGED,
            payload={
                "positionId": str(pos.id),
                "status": pos.lifecycle_status,
                "reason": reason,
                "version": pos.version,
            },
        )
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
                raise PositionServiceError(
                    "HR02_POSITION_NOT_FOUND", "岗位不存在", http_status=404
                )
            if pos.lifecycle_status == HrPosition.LifecycleStatus.CLOSED:
                return pos
            effective_date = timezone.localdate()
            from hr_staff.models import HrStaffAssignment

            active_assignments = HrStaffAssignment.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id=pos.id,
                status="ACTIVE",
                effective_from__lte=effective_date,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=effective_date)
            ).count()
            if active_assignments:
                raise PositionServiceError(
                    "HR02_POSITION_HAS_ACTIVE_ASSIGNMENTS",
                    f"岗位有 {active_assignments} 条生效任职，需先通过 HR03 异动",
                )
            held = HrPositionReservation.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id=pos.id,
                status=HrPositionReservation.Status.HELD,
            ).count()
            if held:
                raise PositionServiceError(
                    "HR02_POSITION_HAS_RESERVATIONS",
                    f"岗位有 {held} 条未处理预占，不能关闭",
                )
            self._append_history(
                pos,
                as_of=effective_date,
                status=HrPosition.LifecycleStatus.CLOSED,
                reason=reason or "CLOSE_POSITION",
            )
            pos.lifecycle_status = HrPosition.LifecycleStatus.CLOSED
            pos.close_reason = reason
            pos.validity_to = effective_date
            pos.version += 1
            pos.save(
                update_fields=[
                    "lifecycle_status",
                    "close_reason",
                    "validity_to",
                    "version",
                ]
            )
            emit_registered_event(
                tenant_id=self.scope.tenant_id,
                event_name=EVENT_POSITION_STATUS_CHANGED,
                payload={
                    "positionId": str(pos.id),
                    "status": pos.lifecycle_status,
                    "reason": reason,
                    "version": pos.version,
                },
            )
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
        """创建预占；可用量 = max - HR03 当前占用 - 未过期 HELD。"""
        count = self._positive_int_value(count, "预占人数")
        try:
            fte = Decimal(str(fte))
            if fte <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise PositionServiceError(
                "HR02_POSITION_FTE_INVALID", "预占 FTE 必须大于 0"
            )
        existing = HrPositionReservation.objects.filter(
            tenant_id=self.scope.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing  # 幂等重试

        # 先清理过期预占，避免过期 HELD 继续占额（总册 50.1）
        self.expire_overdue()
        now = timezone.now()

        if position_id:
            # HrPosition 本身是所有 capacity-sensitive writer 的串行化锚点。
            pos = (
                HrPosition.objects.select_for_update()
                .filter(
                    tenant_id=self.scope.tenant_id,
                    id=position_id,
                    lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
                )
                .first()
            )
            if pos is None:
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE", "岗位不存在或未激活"
                )

            # INV-09：岗位占用不是 HR02 手填字段，必须从 HR03 Assignment Authority 派生。
            # 旧实现只数 HELD reservation，导致 max_incumbents=1 且已有在岗人员时
            # 仍能再次预占。这里在持有 Position 行锁期间把 occupancy 一并计入。
            from hr_staff.services.effective_dated_query_service import (
                EffectiveDatedQueryService,
            )

            occupied = EffectiveDatedQueryService(
                self.scope.tenant_id
            ).position_occupancy_as_of(pos.id, timezone.localdate())
            held = (
                HrPositionReservation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    position_id=pos,
                    status=HrPositionReservation.Status.HELD,
                    expires_at__gt=now,
                ).aggregate(total=Sum("reserved_count"))["total"]
                or 0
            )
            if occupied + held + count > pos.max_incumbents:
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE",
                    f"岗位可用额度不足（已占 {occupied}，预占 {held}，上限 {pos.max_incumbents}）",
                )

        if position_pool_id:
            pool = (
                HrPositionPool.objects.select_for_update()
                .filter(
                    tenant_id=self.scope.tenant_id,
                    id=position_pool_id,
                    status="ACTIVE",
                )
                .first()
            )
            if pool is None:
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE", "岗位池不存在或未激活"
                )
            held = (
                HrPositionReservation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    position_pool_id=pool,
                    status=HrPositionReservation.Status.HELD,
                    expires_at__gt=now,
                ).aggregate(total=Sum("reserved_count"))["total"]
                or 0
            )
            if held + count > pool.authorized_count:
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE", "岗位池可用额度不足"
                )

        effective_expires_at = expires_at or (
            timezone.now()
            + __import__("datetime", fromlist=["timedelta"]).timedelta(days=7)
        )
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
            expires_at=effective_expires_at,
            idempotency_key=idempotency_key,
        )
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_RESERVATION_HELD,
            payload={
                "reservationId": str(reservation.id),
                "positionId": str(position_id or ""),
                "positionPoolId": str(position_pool_id or ""),
                "reservedCount": count,
                "reservedFte": str(fte),
                "expiresAt": effective_expires_at.isoformat(),
                "sourceDomain": source_domain,
                "sourceBusinessType": source_business_type,
                "sourceBusinessId": source_business_id,
            },
            correlation_id=idempotency_key,
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
                raise PositionServiceError(
                    "HR02_POSITION_NOT_FOUND", "预占不存在", http_status=404
                )
            if r.status not in (
                HrPositionReservation.Status.HELD,
                HrPositionReservation.Status.COMMITTED,
            ):
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE", f"预占状态 {r.status} 不可提交"
                )
            r.status = HrPositionReservation.Status.COMMITTED
            r.committed_at = timezone.now()
            r.save(update_fields=["status", "committed_at"])
            emit_registered_event(
                tenant_id=self.scope.tenant_id,
                event_name=EVENT_RESERVATION_COMMITTED,
                payload={
                    "reservationId": str(r.id),
                    "positionId": str(r.position_id_id or ""),
                    "positionPoolId": str(r.position_pool_id_id or ""),
                    "committedAt": r.committed_at.isoformat(),
                },
            )
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
                raise PositionServiceError(
                    "HR02_POSITION_NOT_FOUND", "预占不存在", http_status=404
                )
            if r.status != HrPositionReservation.Status.HELD:
                raise PositionServiceError(
                    "HR02_POSITION_NOT_AVAILABLE", f"预占状态 {r.status} 不可释放"
                )
            r.status = HrPositionReservation.Status.RELEASED
            r.released_at = timezone.now()
            r.save(update_fields=["status", "released_at"])
            emit_registered_event(
                tenant_id=self.scope.tenant_id,
                event_name=EVENT_RESERVATION_RELEASED,
                payload={
                    "reservationId": str(r.id),
                    "positionId": str(r.position_id_id or ""),
                    "positionPoolId": str(r.position_pool_id_id or ""),
                    "releasedAt": r.released_at.isoformat(),
                },
            )
            return r

    @transaction.atomic
    def expire_overdue(self, *, as_of=None) -> int:
        """把已过期（expires_at < now）的 HELD 预占置为 EXPIRED（总册 50.1）。"""
        now = as_of or timezone.now()
        qs = HrPositionReservation.objects.filter(
            tenant_id=self.scope.tenant_id,
            status=HrPositionReservation.Status.HELD,
            expires_at__lt=now,
        ).select_for_update()
        count = qs.update(status=HrPositionReservation.Status.EXPIRED)
        return count
