from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_exit.models import ExitCase, ExitFact
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
        return case, relationship, fact

    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_hr03_failure_keeps_case_and_fact_effect_pending(self, employment_service_cls):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        employment_service_cls.return_value.end_relationship.side_effect = RuntimeError(
            "HR03 relationship termination failed"
        )

        result = service.apply(
            case_id=case.id,
            fact_no="EXIT-001",
            reason_code="VOLUNTARY_RESIGNATION",
        )

        self.assertFalse(result.effective)
        self.assertEqual(case.status, ExitCase.Status.EFFECT_PENDING)
        self.assertEqual(fact.status, ExitFact.Status.EFFECT_PENDING)
        self.assertIn("termination failed", fact.last_effect_error)

    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_effective_is_published_only_after_hr03_relationship_end(self, employment_service_cls):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        ended = SimpleNamespace(id=relationship.id, status="ENDED")
        employment_service_cls.return_value.end_relationship.return_value = ended

        result = service.apply(
            case_id=case.id,
            fact_no="EXIT-001",
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
        self.assertEqual(fact.status, ExitFact.Status.EFFECTIVE)
        self.assertEqual(case.status, ExitCase.Status.EFFECTIVE)
        self.assertEqual(fact.effect_receipt_json["hr03RelationshipStatus"], "ENDED")

    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_already_effective_fact_is_idempotent(self, employment_service_cls):
        service = ExitEffectService(77, actor_user_id=9)
        case, relationship, fact = self._fixtures()
        fact.status = ExitFact.Status.EFFECTIVE
        service._lock_case = MagicMock(return_value=case)
        service._lock_relationship = MagicMock(return_value=relationship)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)

        result = service.apply(case_id=case.id, fact_no="EXIT-001")

        self.assertTrue(result.effective)
        employment_service_cls.assert_not_called()
