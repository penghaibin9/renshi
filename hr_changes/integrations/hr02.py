"""
hr_changes/integrations/hr02.py —— HR02 集成（S4 起，总册 §4.1/§21.4）。

PositionGate：
- reserve_for_case：审批/最终批准前预占目标岗位（idempotency_key=case.id）；
- commit_for_case：生效日提交预占（占额固化）；
- release_for_case：未生效取消时释放预占；
- check_capacity：容量校验（HARD control 下 HELD 也算占用）。

不新建岗位；只读取/预占/提交/释放（HR02 Authority）。所有读写显式 tenant scope。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from hr_changes.constants import ChangeActionCode
from hr_structure.models import HrPositionReservation
from hr_structure.scope import Hr02Scope
from hr_structure.services.position import PositionService, PositionServiceError


class Hr02GateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class PositionGate:
    """HR02 岗位占用/预占门（HR06 消费侧）。"""

    SOURCE_DOMAIN = "HR06"

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise Hr02GateError("TENANT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.scope = Hr02Scope(scope_type="SCHOOL", tenant_id=tenant_id)
        self.service = PositionService(self.scope, actor="HR06")

    def _idempotency_key(self, case_id) -> str:
        return f"HR06-TENANT-{self.tenant_id}-CASE-{case_id}"

    def _assert_case_tenant(self, case) -> None:
        if getattr(case, "tenant_id", None) != self.tenant_id:
            raise Hr02GateError("CROSS_TENANT_CASE", "change case tenant mismatch")

    def needs_position(self, action_code: str) -> bool:
        return action_code in (
            ChangeActionCode.POSITION_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        )

    def target_position(self, case):
        self._assert_case_tenant(case)
        if not self.needs_position(case.action_id.code):
            return None
        position = case.target_position_id
        if position is None:
            return None
        if getattr(position, "tenant_id", None) != self.tenant_id:
            raise Hr02GateError("CROSS_TENANT_POSITION", "target position tenant mismatch")
        return position

    def reserve_for_case(self, case) -> Optional[HrPositionReservation]:
        position = self.target_position(case)
        if position is None:
            return None
        try:
            return self.service.reserve(
                source_domain=self.SOURCE_DOMAIN,
                source_business_type=f"HR06_{case.action_id.code}",
                source_business_id=str(case.id),
                position_id=position.id,
                count=1,
                fte=1.00,
                idempotency_key=self._idempotency_key(case.id),
            )
        except PositionServiceError as exc:
            raise Hr02GateError(
                exc.code,
                exc.args[0] if exc.args else "岗位预占失败",
            )

    def commit_for_case(self, case) -> Optional[HrPositionReservation]:
        self._assert_case_tenant(case)
        reservation = self._get_reservation(case)
        if reservation is None:
            return None
        try:
            return self.service.commit(reservation.id)
        except PositionServiceError as exc:
            raise Hr02GateError(
                exc.code,
                exc.args[0] if exc.args else "岗位预占提交失败",
            )

    def require_commit_for_case(self, case) -> HrPositionReservation:
        """需要岗位的异动必须存在并成功提交预占；不得把缺失/失败当成无事发生。"""
        self._assert_case_tenant(case)
        if not self.needs_position(case.action_id.code):
            raise Hr02GateError(
                "POSITION_RESERVATION_NOT_REQUIRED",
                "当前异动类型不需要岗位预占",
            )
        reservation = self._get_reservation(case)
        if reservation is None:
            raise Hr02GateError(
                "CHANGE_POSITION_RESERVATION_MISSING",
                "目标岗位预占缺失，禁止生效",
            )
        return self.commit_for_case(case)

    def release_for_case(self, case) -> Optional[HrPositionReservation]:
        self._assert_case_tenant(case)
        reservation = self._get_reservation(case)
        if reservation is None or reservation.status != HrPositionReservation.Status.HELD:
            return None
        try:
            return self.service.release(reservation.id)
        except PositionServiceError as exc:
            raise Hr02GateError(
                exc.code,
                exc.args[0] if exc.args else "岗位预占释放失败",
            )

    def _get_reservation(self, case) -> Optional[HrPositionReservation]:
        self._assert_case_tenant(case)
        return (
            HrPositionReservation.objects.filter(
                tenant_id=self.tenant_id,
                source_business_type=f"HR06_{case.action_id.code}",
                source_business_id=str(case.id),
            )
            .order_by("-reserved_at")
            .first()
        )

    def check_capacity(self, case, as_of: Optional[date] = None) -> list[dict]:
        position = self.target_position(case)
        if position is None:
            return []
        from hr_staff.services.effective_dated_query_service import (
            EffectiveDatedQueryService,
        )

        as_of = as_of or date.today()
        occupancy = EffectiveDatedQueryService(self.tenant_id).position_occupancy_as_of(
            position.id,
            as_of,
        )
        held = HrPositionReservation.objects.filter(
            tenant_id=self.tenant_id,
            position_id=position,
            status=HrPositionReservation.Status.HELD,
        ).count()
        if occupancy + held >= position.max_incumbents:
            return [
                {
                    "code": "CHANGE_POSITION_CAPACITY_CONFLICT",
                    "message": (
                        f"目标岗位可用额度不足（已占 {occupancy}，预占 {held}，"
                        f"上限 {position.max_incumbents}）"
                    ),
                }
            ]
        return []
