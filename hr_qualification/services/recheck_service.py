"""
hr_qualification/services/recheck_service.py —— 复核服务（总册 §87-90/§130）。

- 证书失效 → EvidenceUsage 遍历 → 开 RecheckCase
- 复核决策：KEEP / UPGRADE / DOWNGRADE / SUSPEND / REVOKE / EXPIRE
- 证据失效只开 RecheckCase，不自动撤销认定
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hr_qualification.constants import RecheckDecision, RecognitionStatus
from hr_qualification.models import (
    HrDoubleTeacherRecheckCase,
    HrDoubleTeacherRecognition,
    HrEvidenceUsage,
)


class RecheckError(Exception):
    pass


class RecheckService:
    """复核服务。"""

    @staticmethod
    def open_recheck(
        recognition_id: uuid.UUID,
        trigger: str,
        due_at=None,
    ) -> HrDoubleTeacherRecheckCase:
        """开立复核案例。"""
        recognition = HrDoubleTeacherRecognition.objects.get(id=recognition_id)
        recognition.status = RecognitionStatus.UNDER_REVIEW
        recognition.version += 1
        recognition.save()

        return HrDoubleTeacherRecheckCase.objects.create(
            recognition_id=recognition,
            trigger=trigger,
            due_at=due_at,
            status="OPEN",
        )

    @staticmethod
    def decide(
        recheck_id: uuid.UUID,
        decision: str,
        decided_by: int | None = None,
    ) -> HrDoubleTeacherRecheckCase:
        """做出复核决策，联动更新 Recognition 状态。"""
        case = HrDoubleTeacherRecheckCase.objects.get(id=recheck_id)
        case.decision = decision
        case.decided_at = datetime.now(timezone.utc)
        case.decided_by = decided_by
        case.status = "CLOSED"
        case.save()

        recognition = case.recognition_id

        # 联动 Recognition 状态
        decision_map = {
            RecheckDecision.KEEP: RecognitionStatus.ACTIVE,
            RecheckDecision.UPGRADE: RecognitionStatus.ACTIVE,
            RecheckDecision.DOWNGRADE: RecognitionStatus.ACTIVE,
            RecheckDecision.SUSPEND: RecognitionStatus.SUSPENDED,
            RecheckDecision.REVOKE: RecognitionStatus.REVOKED,
            RecheckDecision.EXPIRE: RecognitionStatus.EXPIRED,
        }

        new_status = decision_map.get(decision)
        if new_status:
            recognition.status = new_status
            recognition.version += 1
            recognition.save()

        return case

    @staticmethod
    def on_evidence_invalidated(
        evidence_type: str,
        evidence_ref: str,
    ) -> list[HrDoubleTeacherRecheckCase]:
        """证据失效 → 遍历 EvidenceUsage → 开 RecheckCase。

        总册硬门 §88：证据失效只开 RecheckCase，不自动撤销认定。
        """
        usages = list(
            HrEvidenceUsage.objects.filter(
                evidence_type=evidence_type,
                evidence_ref=evidence_ref,
            ).select_related("recognition_id")
        )

        rechecks: list[HrDoubleTeacherRecheckCase] = []
        seen_recognition_ids: set[uuid.UUID] = set()

        for usage in usages:
            if usage.recognition_id and usage.recognition_id.id not in seen_recognition_ids:
                seen_recognition_ids.add(usage.recognition_id.id)
                rc = RecheckService.open_recheck(
                    recognition_id=usage.recognition_id.id,
                    trigger="CREDENTIAL_REVOKED",
                )
                rechecks.append(rc)

        return rechecks
