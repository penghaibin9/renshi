"""HR16 participant execution lease and transaction-boundary contracts."""

import uuid
from datetime import date

from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from hr_exit.models import ExitCase, ExitEffect
from hr_exit.services.participant_service import ExitParticipantService
from hr_exit.services.saga_service import ExitEffectSagaService


_PROVIDER_ATOMIC_STATES = []


def _outside_atomic_provider(*, tenant_id, case, effect, actor_user_id=None):
    _PROVIDER_ATOMIC_STATES.append(transaction.get_connection().in_atomic_block)
    return {
        "provider": "test",
        "idempotencyKey": effect.idempotency_key,
    }


def _superseding_provider(*, tenant_id, case, effect, actor_user_id=None):
    ExitEffectSagaService(tenant_id, actor_user_id).record_participant(
        effect_id=effect.id,
        participant="IAM",
        status=ExitEffect.ParticipantStatus.RUNNING,
        receipt={
            "leaseToken": "newer-worker-token",
            "leaseStartedAt": timezone.now().isoformat(),
        },
    )
    return {"provider": "stale-worker"}


class ExitParticipantLeaseTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        _PROVIDER_ATOMIC_STATES.clear()
        self.case = ExitCase.objects.create(
            tenant_id=88001,
            case_no=f"EXIT-LEASE-{uuid.uuid4().hex}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.EFFECTIVE,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=date(2026, 8, 31),
        )

    def _effect(self, *, iam_status=ExitEffect.ParticipantStatus.PENDING, iam_receipt=None):
        return ExitEffect.objects.create(
            tenant_id=88001,
            case_id=self.case.id,
            effect_version=ExitEffect.objects.filter(
                tenant_id=88001, case_id=self.case.id
            ).count()
            + 1,
            idempotency_key=f"lease-{uuid.uuid4().hex}",
            status=ExitEffect.Status.APPLYING,
            hr03_status=ExitEffect.ParticipantStatus.SUCCESS,
            iam_status=iam_status,
            iam_receipt_json=iam_receipt or {},
            hr14_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            settlement_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            archive_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
        )

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_lease._outside_atomic_provider"
        },
        HR16_EXIT_PARTICIPANT_LEASE_SECONDS=900,
    )
    def test_active_running_lease_prevents_duplicate_provider_call(self):
        effect = self._effect(
            iam_status=ExitEffect.ParticipantStatus.RUNNING,
            iam_receipt={
                "leaseToken": "active-worker",
                "leaseStartedAt": timezone.now().isoformat(),
            },
        )

        result = ExitParticipantService(88001).execute(
            effect_id=effect.id,
            participant="IAM",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.RUNNING)
        self.assertEqual(_PROVIDER_ATOMIC_STATES, [])

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_lease._outside_atomic_provider"
        }
    )
    def test_provider_executes_outside_database_transaction(self):
        effect = self._effect()

        result = ExitParticipantService(88001).execute(
            effect_id=effect.id,
            participant="IAM",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(_PROVIDER_ATOMIC_STATES, [False])
        self.assertEqual(result.receipt["idempotencyKey"], effect.idempotency_key)

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_lease._superseding_provider"
        }
    )
    def test_stale_worker_result_cannot_overwrite_newer_lease(self):
        effect = self._effect()

        result = ExitParticipantService(88001).execute(
            effect_id=effect.id,
            participant="IAM",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.RUNNING)
        self.assertIn("stale result ignored", result.error)
        effect.refresh_from_db()
        self.assertEqual(effect.iam_status, ExitEffect.ParticipantStatus.RUNNING)
        self.assertEqual(effect.iam_receipt_json["leaseToken"], "newer-worker-token")
