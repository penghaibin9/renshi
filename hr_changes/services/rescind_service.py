"""
hr_changes/services/rescind_service.py —— 异动撤销服务（S7，总册 §36/§37）。

Rescind = 正式撤销已生效业务事件，不是删除。
流程：EFFECTIVE → RESCIND_REQUESTED → RESCIND_APPROVED → RESCIND_APPLYING → RESCINDED。
依赖检查：后续事实建立在此异动上 → DEPENDENT_CHANGES_EXIST 禁止直接撤销，需人工处理。
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import CaseStatus
from hr_changes.models import HrChangeRescind, HrPersonnelChangeCase
from hr_changes.services.state_machine import transition


class RescindServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class RescindService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _get_case_or_deny(self, case_id) -> HrPersonnelChangeCase:
        case = HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise RescindServiceError("CHANGE_NOT_FOUND", "异动案件不存在")
        return case

    # ------------------------------------------------------------------
    def check_dependent_changes(self, case: HrPersonnelChangeCase) -> list[dict]:
        """后续依赖检测：同人、生效日晚于本案件、且仍生效/待生效/应用中。"""
        dependents = (
            HrPersonnelChangeCase.objects.filter(
                tenant_id=self.tenant_id,
                staff_master_id=case.staff_master_id,
                requested_effective_at__gte=case.requested_effective_at,
                status__in=(
                    CaseStatus.EFFECTIVE,
                    CaseStatus.CLOSED,
                    CaseStatus.APPROVED_WAITING_EFFECTIVE,
                    CaseStatus.APPLYING,
                    CaseStatus.CORRECTED,
                ),
            )
            .exclude(id=case.id)
            .order_by("requested_effective_at")
        )
        return [
            {
                "caseId": str(d.id),
                "caseNo": d.case_no,
                "requestedEffectiveAt": d.requested_effective_at.isoformat(),
                "status": d.status,
            }
            for d in dependents
        ]

    @transaction.atomic
    def request_rescind(self, *, case_id, reason: str) -> HrChangeRescind:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.EFFECTIVE:
            raise RescindServiceError(
                "CHANGE_ALREADY_EFFECTIVE", "仅已生效案件可申请撤销"
            )
        dependents = self.check_dependent_changes(case)
        rescind = HrChangeRescind.objects.create(
            tenant_id=self.tenant_id,
            change_case_id=case,
            reason=reason,
            requested_by=self.actor_user_id,
            dependent_blockers_json=dependents,
        )
        if dependents:
            rescind.status = HrChangeRescind.Status.BLOCKED
            rescind.save(update_fields=["status", "dependent_blockers_json"])
            raise RescindServiceError(
                "CHANGE_DEPENDENT_EVENT_EXISTS",
                "存在后续依赖异动，不能直接撤销；需人工处理（chain rollback/rebase）",
            )
        return rescind

    @transaction.atomic
    def approve_rescind(self, rescind_id) -> HrChangeRescind:
        rescind = (
            HrChangeRescind.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=rescind_id)
            .first()
        )
        if rescind is None:
            raise RescindServiceError("CHANGE_NOT_FOUND", "撤销记录不存在")
        if rescind.status != HrChangeRescind.Status.REQUESTED:
            raise RescindServiceError("CHANGE_INVALID_STATE", "仅待审批撤销可批准")
        rescind.status = HrChangeRescind.Status.APPROVED
        rescind.approved_by = self.actor_user_id
        rescind.version += 1
        rescind.save(update_fields=["status", "approved_by", "version", "updated_at"])
        return rescind

    @transaction.atomic
    def execute_rescind(self, rescind_id) -> HrChangeRescind:
        rescind = (
            HrChangeRescind.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=rescind_id)
            .first()
        )
        if rescind is None:
            raise RescindServiceError("CHANGE_NOT_FOUND", "撤销记录不存在")
        if rescind.status != HrChangeRescind.Status.APPROVED:
            raise RescindServiceError("CHANGE_INVALID_STATE", "撤销必须先批准")
        case = self._get_case_or_deny(rescind.change_case_id_id)
        from_status = case.status
        target = transition("rescind", case.status, CaseStatus.RESCINDED)
        case.status = target
        case.version += 1
        case.save(update_fields=["status", "version", "updated_at"])
        from hr_changes.models import HrChangeTransition

        HrChangeTransition.objects.create(
            change_case_id=case,
            tenant_id=self.tenant_id,
            from_status=from_status,
            to_status=target,
            action="rescind",
            actor_id=self.actor_user_id,
            comment="正式撤销已执行",
            snapshot_hash=rescind.restore_snapshot_hash,
        )
        rescind.status = HrChangeRescind.Status.RESCINDED
        rescind.applied_at = timezone.now()
        rescind.version += 1
        rescind.save(update_fields=["status", "applied_at", "version", "updated_at"])
        return rescind
