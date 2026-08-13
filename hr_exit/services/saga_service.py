"""HR16 durable ExitEffect participant ledger and reconciliation rules."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from hr_exit.models import ExitCase, ExitEffect


class ExitSagaError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ExitEffectSagaService:
    PARTICIPANTS = {
        "HR03": ("hr03_status", "hr03_receipt_json"),
        "HR14": ("hr14_status", "hr14_receipt_json"),
        "IAM": ("iam_status", "iam_receipt_json"),
        "SETTLEMENT": ("settlement_status", "settlement_receipt_json"),
        "ARCHIVE": ("archive_status", "archive_receipt_json"),
    }
    FAILURE_STATUSES = {
        ExitEffect.ParticipantStatus.FAILED,
        ExitEffect.ParticipantStatus.UNAVAILABLE,
    }
    ACTIVE_STATUSES = {
        ExitEffect.ParticipantStatus.PENDING,
        ExitEffect.ParticipantStatus.RUNNING,
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExitSagaError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def begin(
        self,
        *,
        case_id,
        idempotency_key: str,
        correlation_id: str = "",
        required_participants: Iterable[str] = (),
    ) -> ExitEffect:
        """Create one effect version, or replay the exact frozen effect payload."""
        key = (idempotency_key or "").strip()
        if not key:
            raise ExitSagaError(
                "EXIT_EFFECT_IDEMPOTENCY_KEY_REQUIRED",
                "effect apply requires an idempotency key",
            )
        if len(key) > 128:
            raise ExitSagaError(
                "EXIT_EFFECT_IDEMPOTENCY_KEY_INVALID",
                "effect idempotency key is limited to 128 characters",
            )
        correlation = str(correlation_id or "").strip()
        if len(correlation) > 128:
            raise ExitSagaError(
                "EXIT_EFFECT_CORRELATION_ID_INVALID",
                "effect correlation id is limited to 128 characters",
            )

        required = {str(value or "").strip().upper() for value in required_participants}
        unknown = required - set(self.PARTICIPANTS)
        if unknown:
            labels = [value or "<blank>" for value in sorted(unknown)]
            raise ExitSagaError(
                "EXIT_EFFECT_PARTICIPANT_UNKNOWN",
                f"unknown effect participants: {', '.join(labels)}",
            )
        required.add("HR03")

        case = (
            ExitCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise ExitSagaError("EXIT_CASE_NOT_FOUND", "exit case not found inside tenant")

        existing = (
            ExitEffect.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, idempotency_key=key)
            .first()
        )
        if existing is not None:
            existing_required = {
                participant
                for participant, (status_field, _receipt_field) in self.PARTICIPANTS.items()
                if getattr(existing, status_field) != ExitEffect.ParticipantStatus.NOT_REQUIRED
            }
            if (
                str(existing.case_id) != str(case.id)
                or str(existing.correlation_id or "").strip() != correlation
                or existing_required != required
            ):
                raise ExitSagaError(
                    "EXIT_EFFECT_IDEMPOTENCY_CONFLICT",
                    "idempotency key already belongs to a different frozen exit effect payload",
                )
            return existing

        current_max = (
            ExitEffect.objects.filter(
                tenant_id=self.tenant_id,
                case_id=case.id,
            ).aggregate(value=Max("effect_version"))["value"]
            or 0
        )
        participant_defaults = {}
        for participant, (status_field, _receipt_field) in self.PARTICIPANTS.items():
            participant_defaults[status_field] = (
                ExitEffect.ParticipantStatus.PENDING
                if participant in required
                else ExitEffect.ParticipantStatus.NOT_REQUIRED
            )

        return ExitEffect.objects.create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            effect_version=current_max + 1,
            idempotency_key=key,
            correlation_id=correlation,
            status=ExitEffect.Status.PENDING,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            **participant_defaults,
        )

    def _derive_status(self, effect: ExitEffect) -> str:
        """Derive saga status without erasing already-applied external facts."""
        hr03 = effect.hr03_status
        if hr03 in self.FAILURE_STATUSES:
            return ExitEffect.Status.FAILED
        if hr03 != ExitEffect.ParticipantStatus.SUCCESS:
            statuses = [
                getattr(effect, status_field)
                for status_field, _ in self.PARTICIPANTS.values()
            ]
            if ExitEffect.ParticipantStatus.RUNNING in statuses:
                return ExitEffect.Status.APPLYING
            return ExitEffect.Status.PENDING

        non_core = [
            getattr(effect, status_field)
            for participant, (status_field, _receipt_field) in self.PARTICIPANTS.items()
            if participant != "HR03"
        ]
        if any(status in self.FAILURE_STATUSES for status in non_core):
            return ExitEffect.Status.PARTIAL_FAILED
        if any(status in self.ACTIVE_STATUSES for status in non_core):
            return ExitEffect.Status.APPLYING
        return ExitEffect.Status.SUCCESS

    @transaction.atomic
    def record_participant(
        self,
        *,
        effect_id,
        participant: str,
        status: str,
        receipt: Optional[Mapping] = None,
        error: str = "",
    ) -> ExitEffect:
        participant = str(participant or "").strip().upper()
        if participant not in self.PARTICIPANTS:
            raise ExitSagaError(
                "EXIT_EFFECT_PARTICIPANT_UNKNOWN",
                f"unknown effect participant: {participant or '<blank>'}",
            )
        valid_statuses = {value for value, _label in ExitEffect.ParticipantStatus.choices}
        if status not in valid_statuses:
            raise ExitSagaError(
                "EXIT_EFFECT_PARTICIPANT_STATUS_INVALID",
                f"invalid participant status: {status}",
            )
        if participant == "HR03" and status == ExitEffect.ParticipantStatus.NOT_REQUIRED:
            raise ExitSagaError(
                "EXIT_EFFECT_HR03_REQUIRED",
                "HR03 is the core employment effect and cannot be NOT_REQUIRED",
            )

        effect = (
            ExitEffect.objects.select_for_update()
            .filter(id=effect_id, tenant_id=self.tenant_id)
            .first()
        )
        if effect is None:
            raise ExitSagaError("EXIT_EFFECT_NOT_FOUND", "exit effect not found inside tenant")

        status_field, receipt_field = self.PARTICIPANTS[participant]
        previous = getattr(effect, status_field)
        previous_required = previous != ExitEffect.ParticipantStatus.NOT_REQUIRED
        next_required = status != ExitEffect.ParticipantStatus.NOT_REQUIRED
        if previous_required != next_required:
            raise ExitSagaError(
                "EXIT_EFFECT_PARTICIPANT_REQUIREMENT_IMMUTABLE",
                f"{participant} required/not-required membership is frozen at saga creation",
            )

        if previous == ExitEffect.ParticipantStatus.SUCCESS:
            if status != ExitEffect.ParticipantStatus.SUCCESS:
                # An externally successful, potentially irreversible participant is
                # an immutable historical observation. Later drift becomes a risk /
                # reconciliation event; never rewrite SUCCESS to make it disappear.
                raise ExitSagaError(
                    "EXIT_EFFECT_SUCCESS_IMMUTABLE",
                    f"{participant} SUCCESS cannot be downgraded",
                )
            frozen_receipt = dict(getattr(effect, receipt_field) or {})
            if receipt is not None and dict(receipt) != frozen_receipt:
                raise ExitSagaError(
                    "EXIT_EFFECT_SUCCESS_RECEIPT_CONFLICT",
                    f"{participant} SUCCESS receipt is immutable",
                )
            if error:
                raise ExitSagaError(
                    "EXIT_EFFECT_SUCCESS_IMMUTABLE",
                    f"{participant} SUCCESS cannot be rewritten with an error",
                )
            return effect

        if status == ExitEffect.ParticipantStatus.NOT_REQUIRED:
            if receipt is not None or error:
                raise ExitSagaError(
                    "EXIT_EFFECT_PARTICIPANT_REQUIREMENT_IMMUTABLE",
                    f"{participant} NOT_REQUIRED cannot carry a receipt or error",
                )
            return effect

        setattr(effect, status_field, status)
        update_fields = [status_field]
        if receipt is not None:
            setattr(effect, receipt_field, dict(receipt))
            update_fields.append(receipt_field)

        if status in self.FAILURE_STATUSES:
            effect.last_error = (error or f"{participant} {status}")[:2000]
            update_fields.append("last_error")
        elif error:
            effect.last_error = error[:2000]
            update_fields.append("last_error")

        derived = self._derive_status(effect)
        if effect.status != derived:
            effect.status = derived
            update_fields.append("status")

        if (
            participant == "HR03"
            and status == ExitEffect.ParticipantStatus.SUCCESS
            and effect.applied_at is None
        ):
            effect.applied_at = timezone.now()
            update_fields.append("applied_at")
        if derived == ExitEffect.Status.SUCCESS and effect.reconciled_at is None:
            effect.reconciled_at = timezone.now()
            update_fields.append("reconciled_at")

        effect.version += 1
        effect.updated_by = self.actor_user_id
        update_fields.extend(["version", "updated_by", "updated_at"])
        effect.save(update_fields=list(dict.fromkeys(update_fields)))
        return effect
