from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.test import TestCase

from hr_exit.models import ExitCase, ExitEffect, ExitFact
from hr_exit.services.effect_service import ExitEffectService


class ExitEffectServiceTests(TestCase):
    def _fixtures(self):
        case = MagicMock()
        case.id = "00000000-0000-0000-0000-000000000101"
        case.person_id = "00000000-0000-0000-0000-000000000201"
        case.employment_relationship_id = "00000000-0000-0000-0000-000000000301"
        case.exit_type = ExitCase.ExitType.RESIGNATION
        case.status = ExitCase.Status.SETTLEMENT
        case.planned_employment_end_date = date(2026, 9, 1)
        case.last_working_date = date(2026, 8, 31)
        case.planned_access_end_at = None

        relationship = SimpleNamespace(
            id=case.employment_relationship_id,
            status="ACTIVE",
        )
        fact = MagicMock()
        fact.id = "00000000-0000-0000-0000-000000000401"
        fact.status = ExitFact.Status.EFFECT_PENDING
        fact.last_effect_error = ""
        fact.effect_receipt_json = {}

        effect = MagicMock()
        effect.id = "00000000-0000-0000-0000-000000000501"
        effect.hr03_status = ExitEffect.ParticipantStatus.PENDING
        return case, relationship, fact, effect

    @patch("hr_exit.services.effect_service.ExitEffectSagaService")
    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_hr03_failure_keeps_pending_and_records_saga_failure(
        self, employment_service_cls, saga_cls
    ):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact, effect = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        saga = saga_cls.return_value
        saga.begin.return_value = effect
        saga.record_participant.return_value = effect
        employment_service_cls.return_value.end_relationship.side_effect = RuntimeError(
            "HR03 relationship termination failed"
        )

        result = service.apply(
            case_id=case.id,
            fact_no="EXIT-001",
            idempotency_key="exit:case-1:v1",
            reason_code="VOLUNTARY_RESIGNATION",
            required_participants=["IAM"],
        )

        self.assertFalse(result.effective)
        self.assertIs(result.effect, effect)
        self.assertEqual(case.status, ExitCase.Status.EFFECT_PENDING)
        self.assertEqual(fact.status, ExitFact.Status.EFFECT_PENDING)
        self.assertIn("termination failed", fact.last_effect_error)
        saga.begin.assert_called_once_with(
            case_id=case.id,
            idempotency_key="exit:case-1:v1",
            correlation_id="",
            required_participants=["IAM"],
        )
        self.assertEqual(
            saga.record_participant.call_args_list,
            [
                call(
                    effect_id=effect.id,
                    participant="HR03",
                    status=ExitEffect.ParticipantStatus.RUNNING,
                ),
                call(
                    effect_id=effect.id,
                    participant="HR03",
                    status=ExitEffect.ParticipantStatus.FAILED,
                    error=fact.last_effect_error,
                ),
            ],
        )

    @patch("hr_exit.services.effect_service.ExitEffectSagaService")
    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_effective_published_only_after_hr03_success_is_recorded(
        self, employment_service_cls, saga_cls
    ):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact, effect = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        saga = saga_cls.return_value
        saga.begin.return_value = effect
        saga.record_participant.return_value = effect
        ended = SimpleNamespace(id=relationship.id, status="ENDED")
        employment_service_cls.return_value.end_relationship.return_value = ended

        result = service.apply(
            case_id=case.id,
            fact_no="EXIT-001",
            idempotency_key="exit:case-1:v1",
            reason_code="VOLUNTARY_RESIGNATION",
        )

        self.assertTrue(result.effective)
        employment_service_cls.return_value.end_relationship.assert_called_once_with(
            relationship_id=relationship.id,
            effective_to=date(2026, 9, 1),
            reason_code="VOLUNTARY_RESIGNATION",
            source_business_type="HR16_EXIT",
            source_business_id=str(fact.id),
        )
        success_call = saga.record_participant.call_args_list[-1]
        self.assertEqual(success_call.kwargs["participant"], "HR03")
        self.assertEqual(
            success_call.kwargs["status"], ExitEffect.ParticipantStatus.SUCCESS
        )
        self.assertEqual(
            success_call.kwargs["receipt"]["hr03RelationshipStatus"], "ENDED"
        )
        self.assertEqual(fact.status, ExitFact.Status.EFFECTIVE)
        self.assertEqual(case.status, ExitCase.Status.EFFECTIVE)

    @patch("hr_exit.services.effect_service.ExitEffectSagaService")
    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_effective_fact_replay_heals_saga_without_recalling_hr03(
        self, employment_service_cls, saga_cls
    ):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact, effect = self._fixtures()
        fact.status = ExitFact.Status.EFFECTIVE
        fact.effect_receipt_json = {"hr03RelationshipId": str(relationship.id)}
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        saga = saga_cls.return_value
        saga.begin.return_value = effect
        saga.record_participant.return_value = effect

        result = service.apply(
            case_id=case.id,
            fact_no="EXIT-001",
            idempotency_key="exit:case-1:v1",
        )

        self.assertTrue(result.effective)
        employment_service_cls.assert_not_called()
        saga.record_participant.assert_called_once_with(
            effect_id=effect.id,
            participant="HR03",
            status=ExitEffect.ParticipantStatus.SUCCESS,
            receipt=fact.effect_receipt_json,
        )
