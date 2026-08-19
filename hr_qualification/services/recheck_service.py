"""HR09 recognition recheck authority.

Evidence invalidation opens a review case; it never silently mutates a formal
recognition result.  Case open/decision paths are transactionally serialized so
worker retries cannot create duplicate review work or rewrite a closed decision.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from hr_qualification.constants import (
    RecheckDecision,
    RecheckTrigger,
    RecognitionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherRecheckCase,
    HrDoubleTeacherRecognition,
    HrEvidenceUsage,
)


class RecheckError(Exception):
    def __init__(self, code: str, message: str | None = None):
        if message is None:
            message = code
            code = "RECHECK_ERROR"
        self.code = code
        super().__init__(message)


_TERMINAL_RECOGNITION_STATUSES = {
    RecognitionStatus.EXPIRED,
    RecognitionStatus.REVOKED,
    RecognitionStatus.SUPERSEDED,
    RecognitionStatus.INVALID,
}


class RecheckService:
    """Recognition recheck service with replay-safe state transitions."""

    @staticmethod
    @transaction.atomic
    def open_recheck(
        recognition_id: uuid.UUID,
        trigger: str,
        due_at=None,
    ) -> HrDoubleTeacherRecheckCase:
        if trigger not in RecheckTrigger.values:
            raise RecheckError(
                "RECHECK_TRIGGER_INVALID",
                f"invalid recheck trigger: {trigger}",
            )

        recognition = HrDoubleTeacherRecognition.objects.select_for_update().get(
            id=recognition_id
        )
        if recognition.status in _TERMINAL_RECOGNITION_STATUSES:
            raise RecheckError(
                "RECHECK_TERMINAL_RECOGNITION",
                f"recognition is {recognition.status}, cannot open recheck",
            )

        # The recognition row lock serializes concurrent duplicate triggers.
        existing = (
            HrDoubleTeacherRecheckCase.objects.filter(
                recognition_id=recognition,
                trigger=trigger,
                status="OPEN",
            )
            .order_by("created_at", "id")
            .first()
        )
        if existing is not None:
            return existing

        prior_status = recognition.status
        if recognition.status != RecognitionStatus.UNDER_REVIEW:
            recognition.status = RecognitionStatus.UNDER_REVIEW
            recognition.version += 1
            recognition.save(update_fields=["status", "version", "updated_at"])

        return HrDoubleTeacherRecheckCase.objects.create(
            recognition_id=recognition,
            trigger=trigger,
            due_at=due_at,
            status="OPEN",
            evidence_snapshot={
                "recognitionStatusBeforeReview": prior_status,
                "recognitionVersionBeforeReview": recognition.version - (
                    1 if prior_status != RecognitionStatus.UNDER_REVIEW else 0
                ),
            },
        )

    @staticmethod
    @transaction.atomic
    def decide(
        recheck_id: uuid.UUID,
        decision: str,
        decided_by: int | None = None,
    ) -> HrDoubleTeacherRecheckCase:
        if decision not in RecheckDecision.values:
            raise RecheckError(
                "RECHECK_DECISION_INVALID",
                f"invalid recheck decision: {decision}",
            )

        case = (
            HrDoubleTeacherRecheckCase.objects.select_for_update()
            .select_related("recognition_id")
            .get(id=recheck_id)
        )
        recognition = HrDoubleTeacherRecognition.objects.select_for_update().get(
            id=case.recognition_id_id
        )

        if case.status == "CLOSED":
            if case.decision == decision:
                return case
            raise RecheckError(
                "RECHECK_DECISION_CONFLICT",
                f"recheck already closed with decision {case.decision}",
            )
        if case.status != "OPEN":
            raise RecheckError(
                "RECHECK_CASE_INVALID_STATE",
                f"recheck is {case.status}, cannot decide",
            )

        # Upgrade/downgrade changes the immutable recognition level.  It must be
        # represented by a new formal recognition that supersedes the old fact;
        # flipping the old row back to ACTIVE would falsely claim the level was
        # changed when no such Authority fact exists.
        if decision in {RecheckDecision.UPGRADE, RecheckDecision.DOWNGRADE}:
            raise RecheckError(
                "RECHECK_LEVEL_CHANGE_REQUIRES_NEW_RECOGNITION",
                "upgrade/downgrade requires a new recognition + supersede flow",
            )

        decision_map = {
            RecheckDecision.KEEP: RecognitionStatus.ACTIVE,
            RecheckDecision.SUSPEND: RecognitionStatus.SUSPENDED,
            RecheckDecision.REVOKE: RecognitionStatus.REVOKED,
            RecheckDecision.EXPIRE: RecognitionStatus.EXPIRED,
            RecheckDecision.NEEDS_FURTHER_REVIEW: RecognitionStatus.UNDER_REVIEW,
        }
        new_status = decision_map[decision]

        case.decision = decision
        case.decided_at = timezone.now()
        case.decided_by = decided_by
        case.status = "CLOSED"
        case.version += 1
        case.save(
            update_fields=[
                "decision",
                "decided_at",
                "decided_by",
                "status",
                "version",
                "updated_at",
            ]
        )

        if recognition.status != new_status:
            recognition.status = new_status
            recognition.version += 1
            recognition.save(update_fields=["status", "version", "updated_at"])

        return case

    @staticmethod
    def on_evidence_invalidated(
        evidence_type: str,
        evidence_ref: str,
    ) -> list[HrDoubleTeacherRecheckCase]:
        """Evidence invalidation opens one replay-safe case per recognition.

        It deliberately does not revoke the recognition automatically.  Repeated
        delivery of the same invalidation is harmless because ``open_recheck``
        serializes on the recognition and reuses an existing open case.
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
                    trigger=RecheckTrigger.CREDENTIAL_REVOKED,
                )
                rechecks.append(rc)

        return rechecks
