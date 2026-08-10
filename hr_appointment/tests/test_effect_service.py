from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_appointment.models import AppointmentApplicationCase, PositionAppointmentFact
from hr_appointment.services.effect_service import AppointmentEffectService


class AppointmentEffectServiceTests(TestCase):
    def _fixtures(self):
        case = MagicMock()
        case.id = "00000000-0000-0000-0000-000000000101"
        case.person_id = "00000000-0000-0000-0000-000000000201"
        case.position_instance_id = 31
        case.requested_level_code = "PRO_LEVEL_7"
        case.status = AppointmentApplicationCase.Status.PUBLICITY

        fact = MagicMock()
        fact.id = "00000000-0000-0000-0000-000000000301"
        fact.status = PositionAppointmentFact.Status.EFFECT_PENDING
        fact.last_effect_error = ""
        fact.effect_receipt_json = {}

        reservation = SimpleNamespace(id=41)
        position = SimpleNamespace(
            id=31,
            organization_id=SimpleNamespace(id=11),
            post_catalog_version_id=SimpleNamespace(id=21),
        )
        staff = SimpleNamespace(id="00000000-0000-0000-0000-000000000401")
        relationship = SimpleNamespace(id="00000000-0000-0000-0000-000000000501")
        return case, fact, reservation, position, staff, relationship

    @patch("hr_structure.services.position.PositionService")
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_provider_failure_keeps_effect_pending_and_does_not_commit_reservation(
        self, assignment_service_cls, position_service_cls
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, reservation, position, staff, relationship = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        service._lock_capacity_receipt = MagicMock(return_value=(reservation, position))
        service._active_staff_relationship = MagicMock(return_value=(staff, relationship))
        assignment_service_cls.return_value.switch_primary.side_effect = RuntimeError(
            "HR03 write failed"
        )

        result = service.apply(
            case_id=case.id,
            appointment_no="APT-001",
            reservation_id=41,
            effective_from=date(2026, 9, 1),
        )

        self.assertFalse(result.effective)
        self.assertEqual(fact.status, PositionAppointmentFact.Status.EFFECT_PENDING)
        self.assertIn("HR03 write failed", fact.last_effect_error)
        self.assertEqual(case.status, AppointmentApplicationCase.Status.EFFECT_PENDING)
        position_service_cls.return_value.commit.assert_not_called()

    @patch("hr_structure.services.position.PositionService")
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_success_requires_hr03_write_then_reservation_commit_before_effective(
        self, assignment_service_cls, position_service_cls
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, reservation, position, staff, relationship = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        service._lock_capacity_receipt = MagicMock(return_value=(reservation, position))
        service._active_staff_relationship = MagicMock(return_value=(staff, relationship))
        assignment = SimpleNamespace(id="00000000-0000-0000-0000-000000000601")
        assignment_service_cls.return_value.switch_primary.return_value = assignment

        result = service.apply(
            case_id=case.id,
            appointment_no="APT-001",
            reservation_id=41,
            effective_from=date(2026, 9, 1),
            level_code="PRO_LEVEL_7",
        )

        self.assertTrue(result.effective)
        assignment_service_cls.return_value.switch_primary.assert_called_once_with(
            employment_relationship_id=relationship,
            effective_from=date(2026, 9, 1),
            organization_id=position.organization_id,
            position_id=position,
            post_catalog_id=position.post_catalog_version_id,
            source_business_type="HR14_APPOINTMENT",
            source_business_id=str(fact.id),
        )
        position_service_cls.return_value.commit.assert_called_once_with(41)
        self.assertEqual(fact.status, PositionAppointmentFact.Status.EFFECTIVE)
        self.assertEqual(case.status, AppointmentApplicationCase.Status.EFFECTIVE)
        self.assertEqual(fact.effect_receipt_json["hr02ReservationId"], 41)
        self.assertEqual(fact.effect_receipt_json["hr02PositionId"], 31)

    def test_already_effective_fact_is_idempotent_and_skips_provider_writes(self):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, *_ = self._fixtures()
        fact.status = PositionAppointmentFact.Status.EFFECTIVE
        service._lock_case = MagicMock(return_value=case)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        service._lock_capacity_receipt = MagicMock()

        result = service.apply(
            case_id=case.id,
            appointment_no="APT-001",
            reservation_id=41,
            effective_from=date(2026, 9, 1),
        )

        self.assertTrue(result.effective)
        service._lock_capacity_receipt.assert_not_called()
