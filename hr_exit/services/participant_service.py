"""Executable non-core participant orchestration for the HR16 ExitEffect saga.

Provider calls are deliberately executed outside database transactions. A short
transaction first claims a durable RUNNING lease; a second short transaction
persists the result only if that exact lease token is still current. This keeps
network/external latency away from row locks and prevents an old worker from
overwriting a newer reconciliation attempt.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_exit.models import ExitCase, ExitEffect
from hr_exit.services.saga_service import ExitEffectSagaService


class ExitParticipantError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ExitParticipantUnavailable(Exception):
    """Provider exists conceptually but is unavailable for this execution."""


@dataclass(frozen=True)
class ExitParticipantResult:
    effect: ExitEffect
    participant: str
    status: str
    receipt: Mapping
    error: str = ""


@dataclass(frozen=True)
class _ParticipantClaim:
    effect: ExitEffect
    case: ExitCase
    lease_token: str


class ExitParticipantService:
    NON_CORE = frozenset(
        {"HR07", "HR14", "IAM", "ASSET", "SETTLEMENT", "FINANCE", "ARCHIVE"}
    )
    BUILTIN_PROVIDERS = {
        "HR07": "hr_contracts.exit_provider.exit_participant_provider",
        "HR14": "hr_appointment.exit_provider.exit_participant_provider",
        "IAM": "hr_exit.services.external_participant_providers.iam_participant_provider",
        "ASSET": "hr_exit.services.external_participant_providers.asset_participant_provider",
        "SETTLEMENT": "hr_payroll.exit_provider.exit_settlement_participant_provider",
        "FINANCE": "hr_exit.services.external_participant_providers.finance_participant_provider",
        "ARCHIVE": "hr_exit.services.archive_transfer_service.archive_participant_provider",
    }
    DEFAULT_LEASE_SECONDS = 900

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExitParticipantError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.saga = ExitEffectSagaService(self.tenant_id, actor_user_id)

    def _lock_effect(self, effect_id) -> ExitEffect:
        effect = (
            ExitEffect.objects.select_for_update()
            .filter(id=effect_id, tenant_id=self.tenant_id)
            .first()
        )
        if effect is None:
            raise ExitParticipantError(
                "EXIT_EFFECT_NOT_FOUND", "exit effect not found inside tenant"
            )
        return effect

    def _case(self, effect: ExitEffect) -> ExitCase:
        case = ExitCase.objects.filter(
            id=effect.case_id,
            tenant_id=self.tenant_id,
        ).first()
        if case is None:
            raise ExitParticipantError(
                "EXIT_CASE_NOT_FOUND", "exit case not found inside tenant"
            )
        return case

    @classmethod
    def _provider_path(cls, participant: str) -> str:
        configured = getattr(settings, "HR16_EXIT_PARTICIPANT_PROVIDERS", {}) or {}
        if isinstance(configured, Mapping) and participant in configured:
            return str(configured.get(participant, "") or "").strip()
        return cls.BUILTIN_PROVIDERS.get(participant, "")

    @classmethod
    def _lease_seconds(cls) -> int:
        raw = getattr(
            settings,
            "HR16_EXIT_PARTICIPANT_LEASE_SECONDS",
            cls.DEFAULT_LEASE_SECONDS,
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = cls.DEFAULT_LEASE_SECONDS
        return max(30, min(value, 86400))

    @staticmethod
    def _lease_started(receipt: Mapping, fallback: datetime) -> datetime:
        raw = str(receipt.get("leaseStartedAt", "") or "").strip()
        if raw:
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if timezone.is_naive(value):
                    value = timezone.make_aware(value, timezone.get_current_timezone())
                return value
            except (TypeError, ValueError):
                pass
        return fallback

    @transaction.atomic
    def _claim(
        self,
        *,
        effect_id,
        participant: str,
    ) -> _ParticipantClaim | ExitParticipantResult:
        """Claim one participant quickly; never call the provider in this transaction."""
        effect = self._lock_effect(effect_id)
        status_field, receipt_field = self.saga.PARTICIPANTS[participant]
        current_status = getattr(effect, status_field)
        current_receipt = getattr(effect, receipt_field) or {}

        if current_status == ExitEffect.ParticipantStatus.NOT_REQUIRED:
            raise ExitParticipantError(
                "EXIT_EFFECT_PARTICIPANT_NOT_REQUIRED",
                f"participant {participant} was not required for this effect",
            )
        if current_status == ExitEffect.ParticipantStatus.SUCCESS:
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=current_status,
                receipt=current_receipt,
            )
        if effect.hr03_status != ExitEffect.ParticipantStatus.SUCCESS:
            raise ExitParticipantError(
                "EXIT_EFFECT_CORE_NOT_EFFECTIVE",
                "non-core participants cannot execute before HR03 employment effect succeeds",
            )

        if current_status == ExitEffect.ParticipantStatus.RUNNING:
            lease_started = self._lease_started(
                current_receipt if isinstance(current_receipt, Mapping) else {},
                effect.updated_at,
            )
            if lease_started > timezone.now() - timedelta(seconds=self._lease_seconds()):
                return ExitParticipantResult(
                    effect=effect,
                    participant=participant,
                    status=ExitEffect.ParticipantStatus.RUNNING,
                    receipt={},
                    error="participant already has an active execution lease",
                )

        case = self._case(effect)
        lease_token = uuid.uuid4().hex
        lease_receipt = {
            "leaseToken": lease_token,
            "leaseStartedAt": timezone.now().isoformat(),
        }
        effect = self.saga.record_participant(
            effect_id=effect.id,
            participant=participant,
            status=ExitEffect.ParticipantStatus.RUNNING,
            receipt=lease_receipt,
        )
        return _ParticipantClaim(
            effect=effect,
            case=case,
            lease_token=lease_token,
        )

    @transaction.atomic
    def _finish_claim(
        self,
        *,
        effect_id,
        participant: str,
        lease_token: str,
        status: str,
        receipt: Optional[Mapping] = None,
        error: str = "",
    ) -> ExitParticipantResult:
        """Persist a result only while the caller still owns the RUNNING lease."""
        effect = self._lock_effect(effect_id)
        status_field, receipt_field = self.saga.PARTICIPANTS[participant]
        current_status = getattr(effect, status_field)
        current_receipt = getattr(effect, receipt_field) or {}

        if current_status == ExitEffect.ParticipantStatus.SUCCESS:
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=current_status,
                receipt=current_receipt,
            )

        current_token = (
            str(current_receipt.get("leaseToken", "") or "")
            if isinstance(current_receipt, Mapping)
            else ""
        )
        if (
            current_status != ExitEffect.ParticipantStatus.RUNNING
            or current_token != lease_token
        ):
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=current_status,
                receipt=(current_receipt if isinstance(current_receipt, Mapping) else {}),
                error="participant execution lease was superseded; stale result ignored",
            )

        clean_receipt = dict(receipt or {})
        effect = self.saga.record_participant(
            effect_id=effect.id,
            participant=participant,
            status=status,
            receipt=clean_receipt,
            error=error,
        )
        return ExitParticipantResult(
            effect=effect,
            participant=participant,
            status=status,
            receipt=clean_receipt,
            error=error,
        )

    def execute(self, *, effect_id, participant: str) -> ExitParticipantResult:
        participant = str(participant or "").strip().upper()
        if participant not in self.NON_CORE:
            raise ExitParticipantError(
                "EXIT_EFFECT_PARTICIPANT_NOT_EXECUTABLE",
                f"participant {participant or '<blank>'} is not a non-core executable participant",
            )

        claimed = self._claim(effect_id=effect_id, participant=participant)
        if isinstance(claimed, ExitParticipantResult):
            return claimed

        provider_path = self._provider_path(participant)
        if not provider_path:
            message = f"no formal {participant} provider is registered"
            return self._finish_claim(
                effect_id=claimed.effect.id,
                participant=participant,
                lease_token=claimed.lease_token,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )

        try:
            provider = import_string(provider_path)
        except Exception as exc:
            message = f"provider import failed: {exc}"[:2000]
            return self._finish_claim(
                effect_id=claimed.effect.id,
                participant=participant,
                lease_token=claimed.lease_token,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )

        try:
            # Deliberately outside transaction.atomic: providers may perform
            # external I/O and must use effect.idempotency_key for replay safety.
            receipt = provider(
                tenant_id=self.tenant_id,
                case=claimed.case,
                effect=claimed.effect,
                actor_user_id=self.actor_user_id,
            )
            if not isinstance(receipt, Mapping):
                raise TypeError("participant provider must return a mapping receipt")
        except ExitParticipantUnavailable as exc:
            message = str(exc)[:2000]
            return self._finish_claim(
                effect_id=claimed.effect.id,
                participant=participant,
                lease_token=claimed.lease_token,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )
        except Exception as exc:
            message = str(exc)[:2000]
            return self._finish_claim(
                effect_id=claimed.effect.id,
                participant=participant,
                lease_token=claimed.lease_token,
                status=ExitEffect.ParticipantStatus.FAILED,
                receipt={},
                error=message,
            )

        return self._finish_claim(
            effect_id=claimed.effect.id,
            participant=participant,
            lease_token=claimed.lease_token,
            status=ExitEffect.ParticipantStatus.SUCCESS,
            receipt=dict(receipt),
        )

    def reconcile(self, *, effect_id) -> list[ExitParticipantResult]:
        effect = ExitEffect.objects.filter(
            id=effect_id,
            tenant_id=self.tenant_id,
        ).first()
        if effect is None:
            raise ExitParticipantError(
                "EXIT_EFFECT_NOT_FOUND", "exit effect not found inside tenant"
            )
        results = []
        for participant in sorted(self.NON_CORE):
            status_field, _receipt_field = self.saga.PARTICIPANTS[participant]
            if getattr(effect, status_field) == ExitEffect.ParticipantStatus.NOT_REQUIRED:
                continue
            result = self.execute(effect_id=effect.id, participant=participant)
            results.append(result)
            effect = result.effect
        return results
