import uuid
from datetime import date

from django.test import TestCase, override_settings

from hr_exit.models import ExitCase, ExitEffect
from hr_exit.services.participant_service import (
    ExitParticipantError,
    ExitParticipantService,
    ExitParticipantUnavailable,
)


def successful_iam_provider(*, tenant_id, case, effect, actor_user_id=None):
    return {
        "provider": "test-iam",
        "tenantId": tenant_id,
        "caseId": str(case.id),
        "effectId": str(effect.id),
        "actorUserId": actor_user_id,
    }


def failed_iam_provider(**_kwargs):
    raise RuntimeError("IAM deactivation failed")


def unavailable_archive_provider(**_kwargs):
    raise ExitParticipantUnavailable("archive provider maintenance window")


class ExitParticipantServiceTests(TestCase):
    def _case(self):
        return ExitCase.objects.create(
            tenant_id=77,
            case_no=f"EXIT-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.EFFECTIVE,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=date(2026, 9, 1),
        )

    def _effect(self, *, participant="IAM", hr03_status=ExitEffect.ParticipantStatus.SUCCESS):
        case = self._case()
        kwargs = {
            "hr03_status": hr03_status,
            "hr14_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "iam_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "settlement_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "archive_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
        }
        field = {
            "HR14": "hr14_status",
            "IAM": "iam_status",
            "SETTLEMENT": "settlement_status",
            "ARCHIVE": "archive_status",
        }[participant]
        kwargs[field] = ExitEffect.ParticipantStatus.PENDING
        effect = ExitEffect.objects.create(
            tenant_id=77,
            case_id=case.id,
            effect_version=1,
            idempotency_key=f"IDEM-{uuid.uuid4().hex}",
            status=ExitEffect.Status.PENDING,
            **kwargs,
        )
        return case, effect

    def test_missing_provider_is_unavailable_not_fake_success(self):
        _, effect = self._effect(participant="IAM")

        result = ExitParticipantService(77, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="IAM",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.UNAVAILABLE)
        self.assertIn("IAM provider URL/token is not configured", result.error)
        effect.refresh_from_db()
        self.assertEqual(effect.iam_status, ExitEffect.ParticipantStatus.UNAVAILABLE)
        self.assertEqual(effect.status, ExitEffect.Status.PARTIAL_FAILED)

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_service.successful_iam_provider"
        }
    )
    def test_registered_provider_success_persists_receipt_and_completes_saga(self):
        case, effect = self._effect(participant="IAM")

        result = ExitParticipantService(77, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="iam",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(result.receipt["provider"], "test-iam")
        self.assertEqual(result.receipt["caseId"], str(case.id))
        effect.refresh_from_db()
        self.assertEqual(effect.iam_status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(effect.iam_receipt_json["provider"], "test-iam")
        self.assertEqual(effect.status, ExitEffect.Status.SUCCESS)

        replay = ExitParticipantService(77, actor_user_id=99).execute(
            effect_id=effect.id,
            participant="IAM",
        )
        self.assertEqual(replay.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(replay.receipt, effect.iam_receipt_json)

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_service.failed_iam_provider"
        }
    )
    def test_provider_exception_becomes_failed_and_preserves_core_effect(self):
        _, effect = self._effect(participant="IAM")

        result = ExitParticipantService(77).execute(
            effect_id=effect.id,
            participant="IAM",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.FAILED)
        self.assertIn("IAM deactivation failed", result.error)
        effect.refresh_from_db()
        self.assertEqual(effect.hr03_status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(effect.iam_status, ExitEffect.ParticipantStatus.FAILED)
        self.assertEqual(effect.status, ExitEffect.Status.PARTIAL_FAILED)

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "ARCHIVE": "hr_exit.tests.test_participant_service.unavailable_archive_provider"
        }
    )
    def test_provider_declared_unavailable_is_retryable_unavailable(self):
        _, effect = self._effect(participant="ARCHIVE")

        result = ExitParticipantService(77).execute(
            effect_id=effect.id,
            participant="ARCHIVE",
        )

        self.assertEqual(result.status, ExitEffect.ParticipantStatus.UNAVAILABLE)
        self.assertIn("maintenance window", result.error)

    def test_non_core_cannot_run_before_hr03_success(self):
        _, effect = self._effect(
            participant="IAM",
            hr03_status=ExitEffect.ParticipantStatus.PENDING,
        )

        with self.assertRaises(ExitParticipantError) as ctx:
            ExitParticipantService(77).execute(
                effect_id=effect.id,
                participant="IAM",
            )

        self.assertEqual(ctx.exception.code, "EXIT_EFFECT_CORE_NOT_EFFECTIVE")
        effect.refresh_from_db()
        self.assertEqual(effect.iam_status, ExitEffect.ParticipantStatus.PENDING)

    def test_not_required_and_hr03_participants_cannot_be_manually_executed(self):
        _, effect = self._effect(participant="IAM")
        effect.iam_status = ExitEffect.ParticipantStatus.NOT_REQUIRED
        effect.save(update_fields=["iam_status", "updated_at"])

        with self.assertRaises(ExitParticipantError) as ctx:
            ExitParticipantService(77).execute(
                effect_id=effect.id,
                participant="IAM",
            )
        self.assertEqual(ctx.exception.code, "EXIT_EFFECT_PARTICIPANT_NOT_REQUIRED")

        with self.assertRaises(ExitParticipantError) as ctx:
            ExitParticipantService(77).execute(
                effect_id=effect.id,
                participant="HR03",
            )
        self.assertEqual(ctx.exception.code, "EXIT_EFFECT_PARTICIPANT_NOT_EXECUTABLE")

    @override_settings(
        HR16_EXIT_PARTICIPANT_PROVIDERS={
            "IAM": "hr_exit.tests.test_participant_service.successful_iam_provider"
        }
    )
    def test_cross_tenant_effect_is_not_executable(self):
        _, effect = self._effect(participant="IAM")

        with self.assertRaises(ExitParticipantError) as ctx:
            ExitParticipantService(88).execute(
                effect_id=effect.id,
                participant="IAM",
            )

        self.assertEqual(ctx.exception.code, "EXIT_EFFECT_NOT_FOUND")
