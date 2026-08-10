from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_exit.models import ExitEffect
from hr_exit.services.saga_service import ExitEffectSagaService, ExitSagaError


class ExitEffectSagaServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = ExitEffectSagaService(77, actor_user_id=9)

    def _effect(self, **overrides):
        values = {
            "hr03_status": ExitEffect.ParticipantStatus.SUCCESS,
            "hr14_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "iam_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "settlement_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
            "archive_status": ExitEffect.ParticipantStatus.NOT_REQUIRED,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_hr03_success_plus_iam_failure_is_partial_failed_not_rollback(self):
        effect = self._effect(iam_status=ExitEffect.ParticipantStatus.FAILED)

        status = self.service._derive_status(effect)

        self.assertEqual(status, ExitEffect.Status.PARTIAL_FAILED)
        self.assertEqual(effect.hr03_status, ExitEffect.ParticipantStatus.SUCCESS)

    def test_hr03_failure_is_core_effect_failure(self):
        effect = self._effect(hr03_status=ExitEffect.ParticipantStatus.UNAVAILABLE)
        self.assertEqual(self.service._derive_status(effect), ExitEffect.Status.FAILED)

    def test_pending_non_core_participant_keeps_successful_hr03_effect_applying(self):
        effect = self._effect(hr14_status=ExitEffect.ParticipantStatus.PENDING)
        self.assertEqual(self.service._derive_status(effect), ExitEffect.Status.APPLYING)

    @patch("hr_exit.services.saga_service.ExitEffect.objects")
    @patch("hr_exit.services.saga_service.ExitCase.objects")
    def test_begin_is_tenant_scoped_and_replays_same_idempotency_key(
        self, case_objects, effect_objects
    ):
        case = SimpleNamespace(id="case-1")
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        existing = SimpleNamespace(case_id="case-1")
        effect_objects.select_for_update.return_value.filter.return_value.first.return_value = existing

        result = self.service.begin(case_id="case-1", idempotency_key="exit:case-1:v1")

        self.assertIs(result, existing)
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        effect_objects.select_for_update.return_value.filter.assert_called_once_with(
            tenant_id=77, idempotency_key="exit:case-1:v1"
        )
        effect_objects.create.assert_not_called()

    @patch("hr_exit.services.saga_service.ExitEffect.objects")
    @patch("hr_exit.services.saga_service.ExitCase.objects")
    def test_new_effect_marks_only_required_non_core_participants_pending(
        self, case_objects, effect_objects
    ):
        case = SimpleNamespace(id="case-1")
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        effect_objects.select_for_update.return_value.filter.return_value.first.return_value = None
        aggregate_qs = MagicMock()
        aggregate_qs.aggregate.return_value = {"value": 2}
        effect_objects.filter.return_value = aggregate_qs
        created = MagicMock()
        effect_objects.create.return_value = created

        result = self.service.begin(
            case_id="case-1",
            idempotency_key="exit:case-1:v3",
            required_participants=["IAM", "ARCHIVE"],
        )

        self.assertIs(result, created)
        kwargs = effect_objects.create.call_args.kwargs
        self.assertEqual(kwargs["effect_version"], 3)
        self.assertEqual(kwargs["hr03_status"], ExitEffect.ParticipantStatus.PENDING)
        self.assertEqual(kwargs["iam_status"], ExitEffect.ParticipantStatus.PENDING)
        self.assertEqual(kwargs["archive_status"], ExitEffect.ParticipantStatus.PENDING)
        self.assertEqual(kwargs["hr14_status"], ExitEffect.ParticipantStatus.NOT_REQUIRED)
        self.assertEqual(kwargs["settlement_status"], ExitEffect.ParticipantStatus.NOT_REQUIRED)

    def test_effect_requires_stable_idempotency_key(self):
        with self.assertRaises(ExitSagaError) as cm:
            self.service.begin(case_id="case-1", idempotency_key="")
        self.assertEqual(cm.exception.code, "EXIT_EFFECT_IDEMPOTENCY_KEY_REQUIRED")

    @patch("hr_exit.services.saga_service.ExitEffect.objects")
    def test_successful_irreversible_participant_cannot_be_downgraded(self, effect_objects):
        effect = MagicMock()
        effect.hr03_status = ExitEffect.ParticipantStatus.SUCCESS
        effect_objects.select_for_update.return_value.filter.return_value.first.return_value = effect

        with self.assertRaises(ExitSagaError) as cm:
            self.service.record_participant(
                effect_id="effect-1",
                participant="HR03",
                status=ExitEffect.ParticipantStatus.FAILED,
                error="late failure",
            )

        self.assertEqual(cm.exception.code, "EXIT_EFFECT_SUCCESS_IMMUTABLE")
        effect.save.assert_not_called()

    def test_hr03_can_never_be_not_required(self):
        with self.assertRaises(ExitSagaError) as cm:
            self.service.record_participant(
                effect_id="effect-1",
                participant="HR03",
                status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            )
        self.assertEqual(cm.exception.code, "EXIT_EFFECT_HR03_REQUIRED")
