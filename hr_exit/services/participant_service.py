"""Executable non-core participant orchestration for the HR16 ExitEffect saga.

Providers are registered explicitly through ``HR16_EXIT_PARTICIPANT_PROVIDERS``
in Django settings, mapping HR14/IAM/SETTLEMENT/ARCHIVE to importable callables.
A provider is never inferred from the presence of a legacy table or page.
Missing providers become UNAVAILABLE; provider exceptions become FAILED; only a
successful provider call returning a mapping can become SUCCESS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string

from hr_exit.models import ExitCase, ExitEffect
from hr_exit.services.saga_service import ExitEffectSagaService, ExitSagaError


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


class ExitParticipantService:
    NON_CORE = frozenset({"HR14", "IAM", "SETTLEMENT", "ARCHIVE"})

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

    @staticmethod
    def _provider_path(participant: str) -> str:
        configured = getattr(settings, "HR16_EXIT_PARTICIPANT_PROVIDERS", {}) or {}
        if not isinstance(configured, Mapping):
            return ""
        return str(configured.get(participant, "") or "").strip()

    @transaction.atomic
    def execute(self, *, effect_id, participant: str) -> ExitParticipantResult:
        participant = str(participant or "").strip().upper()
        if participant not in self.NON_CORE:
            raise ExitParticipantError(
                "EXIT_EFFECT_PARTICIPANT_NOT_EXECUTABLE",
                f"participant {participant or '<blank>'} is not a non-core executable participant",
            )

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

        case = self._case(effect)
        effect = self.saga.record_participant(
            effect_id=effect.id,
            participant=participant,
            status=ExitEffect.ParticipantStatus.RUNNING,
        )

        provider_path = self._provider_path(participant)
        if not provider_path:
            message = f"no formal {participant} provider is registered"
            effect = self.saga.record_participant(
                effect_id=effect.id,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                error=message,
            )
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )

        try:
            provider = import_string(provider_path)
        except Exception as exc:
            message = f"provider import failed: {exc}"[:2000]
            effect = self.saga.record_participant(
                effect_id=effect.id,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                error=message,
            )
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )

        try:
            receipt = provider(
                tenant_id=self.tenant_id,
                case=case,
                effect=effect,
                actor_user_id=self.actor_user_id,
            )
            if not isinstance(receipt, Mapping):
                raise TypeError("participant provider must return a mapping receipt")
        except ExitParticipantUnavailable as exc:
            message = str(exc)[:2000]
            effect = self.saga.record_participant(
                effect_id=effect.id,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                error=message,
            )
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=ExitEffect.ParticipantStatus.UNAVAILABLE,
                receipt={},
                error=message,
            )
        except Exception as exc:
            message = str(exc)[:2000]
            effect = self.saga.record_participant(
                effect_id=effect.id,
                participant=participant,
                status=ExitEffect.ParticipantStatus.FAILED,
                error=message,
            )
            return ExitParticipantResult(
                effect=effect,
                participant=participant,
                status=ExitEffect.ParticipantStatus.FAILED,
                receipt={},
                error=message,
            )

        effect = self.saga.record_participant(
            effect_id=effect.id,
            participant=participant,
            status=ExitEffect.ParticipantStatus.SUCCESS,
            receipt=dict(receipt),
        )
        return ExitParticipantResult(
            effect=effect,
            participant=participant,
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
