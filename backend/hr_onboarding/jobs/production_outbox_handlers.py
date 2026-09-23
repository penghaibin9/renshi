"""Production-safe HR05 outbox handlers for the monolith deployment.

HR05's activation command already commits HR03 person/staff/employment/assignment
facts and the HR02 reservation in the same business transaction.  Replaying the
same commands from the outbox would duplicate authority facts.  These handlers
therefore act as *authority publication receipts*: they re-read the sealed source
fact and acknowledge only when the durable event payload is consistent with it.

This makes the outbox a real continuously-consumed reliability boundary without
turning notifications into a second writer of HR authority data.  Downstream
modules in this monolith read the source-domain providers/authority facts; an
external event bridge can be added separately without changing source truth.
"""

from __future__ import annotations

from hr_onboarding.constants import ProbationResult, ProbationStatus
from hr_onboarding.jobs.outbox_dispatcher import (
    DispatchResult,
    OutboxEnvelope,
    OutboxHandlerRegistry,
)
from hr_onboarding.models import (
    HrOnboardingActivationAmendment,
    HrOnboardingActivationSnapshot,
    HrProbationCase,
)


def _retry(code: str) -> DispatchResult:
    return DispatchResult.retry(code)


def _staff_activated(envelope: OutboxEnvelope) -> DispatchResult:
    snapshot = (
        HrOnboardingActivationSnapshot.objects.filter(
            tenant_id=envelope.tenant_id,
            case_id=envelope.aggregate_id,
        )
        .order_by("-created_at")
        .first()
    )
    if snapshot is None:
        return _retry("HR05_OUTBOX_ACTIVATION_SNAPSHOT_NOT_FOUND")
    expected_staff = str(snapshot.staff_master_id or "")
    event_staff = str(envelope.payload.get("staff_master_id") or "")
    if not expected_staff or event_staff != expected_staff:
        return _retry("HR05_OUTBOX_ACTIVATION_STAFF_MISMATCH")
    if not snapshot.content_hash or snapshot.content_hash != snapshot.calculate_content_hash():
        return _retry("HR05_OUTBOX_ACTIVATION_HASH_MISMATCH")
    return DispatchResult.ack(f"hr05-authority:activation:{snapshot.id}")


def _probation(envelope: OutboxEnvelope, *, expected_status: str, expected_result: str) -> DispatchResult:
    probation = HrProbationCase.objects.filter(
        tenant_id=envelope.tenant_id,
        id=envelope.aggregate_id,
    ).first()
    if probation is None:
        return _retry("HR05_OUTBOX_PROBATION_NOT_FOUND")
    if probation.status != expected_status or probation.result != expected_result:
        return _retry("HR05_OUTBOX_PROBATION_STATE_MISMATCH")
    payload_staff = str(envelope.payload.get("staff_master_id") or "")
    if payload_staff and payload_staff != str(probation.staff_master_id or ""):
        return _retry("HR05_OUTBOX_PROBATION_STAFF_MISMATCH")
    return DispatchResult.ack(f"hr05-authority:probation:{probation.id}:{expected_status}")


def _probation_confirmed(envelope: OutboxEnvelope) -> DispatchResult:
    return _probation(
        envelope,
        expected_status=ProbationStatus.CONFIRMED,
        expected_result=ProbationResult.CONFIRMED,
    )


def _probation_failed(envelope: OutboxEnvelope) -> DispatchResult:
    return _probation(
        envelope,
        expected_status=ProbationStatus.FAILED,
        expected_result=ProbationResult.FAILED,
    )


def _activation_amendment(envelope: OutboxEnvelope) -> DispatchResult:
    amendment_id = str(envelope.payload.get("amendment_id") or "")
    amendment = HrOnboardingActivationAmendment.objects.filter(
        tenant_id=envelope.tenant_id,
        id=amendment_id,
        snapshot_id=envelope.aggregate_id,
    ).first()
    if amendment is None:
        return _retry("HR05_OUTBOX_ACTIVATION_AMENDMENT_NOT_FOUND")
    if str(envelope.payload.get("action") or "") != amendment.action:
        return _retry("HR05_OUTBOX_ACTIVATION_AMENDMENT_ACTION_MISMATCH")
    if str(envelope.payload.get("content_hash") or "") != amendment.content_hash:
        return _retry("HR05_OUTBOX_ACTIVATION_AMENDMENT_HASH_MISMATCH")
    if not amendment.content_hash or amendment.content_hash != amendment.calculate_content_hash():
        return _retry("HR05_OUTBOX_ACTIVATION_AMENDMENT_TAMPERED")
    return DispatchResult.ack(f"hr05-authority:activation-amendment:{amendment.id}")


def build_production_registry() -> OutboxHandlerRegistry:
    registry = OutboxHandlerRegistry()
    registry.register("StaffActivated", _staff_activated)
    registry.register("ProbationConfirmed", _probation_confirmed)
    registry.register("ProbationFailed", _probation_failed)
    registry.register("ActivationFactCorrected", _activation_amendment)
    registry.register("ActivationFactRevoked", _activation_amendment)
    return registry
