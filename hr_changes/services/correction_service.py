"""
hr_changes/services/correction_service.py —— 异动纠错服务（S7，总册 §34/§35）。

Correction ≠ Change：发现原记录录错，走受控流程，不伪造成第二次业务异动。
- 仅可对 EFFECTIVE 案件发起；
- 高权限（hr.change.correct）审批；
- 应用时计算前后 snapshot hash，案件状态转 CORRECTED；
- 若 correction 影响下游历史事实必须执行 Impact Analysis（V1 至少记录）。

禁止：无审批 correction；原地修改已生效 snapshot。
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import CaseStatus
from hr_changes.models import HrChangeCorrection, HrChangeEffectiveSnapshot, HrPersonnelChangeCase
from hr_changes.services.state_machine import transition


class CorrectionServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class CorrectionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _get_case_or_deny(self, case_id) -> HrPersonnelChangeCase:
        case = HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise CorrectionServiceError("CHANGE_NOT_FOUND", "异动案件不存在")
        return case

    def _get_correction_or_deny(self, correction_id) -> HrChangeCorrection:
        correction = (
            HrChangeCorrection.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=correction_id)
            .first()
        )
        if correction is None:
            raise CorrectionServiceError("CHANGE_NOT_FOUND", "纠错记录不存在")
        return correction

    # ------------------------------------------------------------------
    @transaction.atomic
    def create_correction(
        self,
        *,
        case_id,
        correction_type: str,
        requested_values: dict,
        reason: str,
    ) -> HrChangeCorrection:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.EFFECTIVE:
            raise CorrectionServiceError(
                "CHANGE_INVALID_STATE", "仅已生效案件可纠错"
            )
        previous_hash = ""
        snapshot = HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).first()
        if snapshot:
            previous_hash = snapshot.checksum
        correction = HrChangeCorrection.objects.create(
            tenant_id=self.tenant_id,
            change_case_id=case,
            correction_type=correction_type,
            requested_values_json=requested_values or {},
            reason=reason,
            requested_by=self.actor_user_id,
            previous_snapshot_hash=previous_hash,
        )
        return correction

    @transaction.atomic
    def submit(self, correction_id) -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if correction.status != HrChangeCorrection.Status.DRAFT:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅草稿纠错可提交")
        correction.status = HrChangeCorrection.Status.SUBMITTED
        correction.version += 1
        correction.save(update_fields=["status", "version", "updated_at"])
        return correction

    @transaction.atomic
    def approve(self, correction_id, *, comment: str = "") -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if correction.status != HrChangeCorrection.Status.SUBMITTED:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅已提交纠错可批准")
        correction.status = HrChangeCorrection.Status.APPROVED
        correction.approved_by = self.actor_user_id
        correction.version += 1
        correction.save(update_fields=["status", "approved_by", "version", "updated_at"])
        return correction

    @transaction.atomic
    def reject(self, correction_id, *, comment: str = "") -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if correction.status != HrChangeCorrection.Status.SUBMITTED:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅已提交纠错可驳回")
        correction.status = HrChangeCorrection.Status.REJECTED
        correction.version += 1
        correction.save(update_fields=["status", "version", "updated_at"])
        return correction

    @transaction.atomic
    def apply(self, correction_id) -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if correction.status != HrChangeCorrection.Status.APPROVED:
            raise CorrectionServiceError(
                "CHANGE_CORRECTION_REQUIRES_APPROVAL", "纠错必须先审批"
            )
        case = self._get_case_or_deny(correction.change_case_id_id)
        new_hash = hashlib.sha256(
            json.dumps(
                {
                    "case": str(case.id),
                    "correction": str(correction.id),
                    "values": correction.requested_values_json,
                    "appliedAt": timezone.now().isoformat(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        correction.new_snapshot_hash = new_hash
        correction.status = HrChangeCorrection.Status.APPLIED
        correction.applied_at = timezone.now()
        correction.version += 1
        correction.save(
            update_fields=["new_snapshot_hash", "status", "applied_at", "version", "updated_at"]
        )
        # 案件状态转 CORRECTED（正式更正），并记录 transition
        from hr_changes.models import HrChangeTransition

        from_status = case.status
        target = transition("correct", case.status, CaseStatus.CORRECTED)
        case.status = target
        case.version += 1
        case.save(update_fields=["status", "version", "updated_at"])
        HrChangeTransition.objects.create(
            change_case_id=case,
            tenant_id=self.tenant_id,
            from_status=from_status,
            to_status=target,
            action="correct",
            actor_id=self.actor_user_id,
            comment="数据纠错已应用",
            snapshot_hash=new_hash,
        )
        return correction
