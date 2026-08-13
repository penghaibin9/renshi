from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import AppointmentApplicationCase, PositionAppointmentFact
from hr_appointment.services.effect_service import AppointmentEffectError, AppointmentEffectService
from hr_appointment.services.publicity_service import AppointmentPublicityError


class AppointmentEffectServiceTests(TestCase):
    def _fixtures(self):
        case = MagicMock()
        case.id = "00000000-0000-0000-0000-000000000101"
        case.case_no = "CASE-000101"
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
        publicity = SimpleNamespace(id="00000000-0000-0000-0000-000000000701")
        return case, fact, reservation, position, staff, relationship, publicity

    @patch("hr_structure.models.HrPosition.objects")
    @patch("hr_structure.models.HrPositionReservation.objects")
    def test_capacity_receipt_requires_explicit_hr14_source_domain(
        self, reservation_objects, position_objects
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, *_ = self._fixtures()
        reservation = SimpleNamespace(
            id=41,
            status="HELD",
            expires_at=timezone.now() + __import__("datetime").timedelta(days=1),
            position_id_id=case.position_instance_id,
            source_domain="",
            source_business_id=str(case.id),
        )
        reservation_objects.select_for_update.return_value.filter.return_value.first.return_value = reservation

        with self.assertRaises(AppointmentEffectError) as ctx:
            service._lock_capacity_receipt(case, reservation.id)

        self.assertEqual(ctx.exception.code, "APPOINTMENT_RESERVATION_SOURCE_MISMATCH")
        position_objects.select_for_update.assert_not_called()

    @patch("hr_structure.models.HrPosition.objects")
    @patch("hr_structure.models.HrPositionReservation.objects")
    def test_capacity_receipt_cannot_be_stolen_from_another_hr14_case(
        self, reservation_objects, position_objects
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, *_ = self._fixtures()
        reservation = SimpleNamespace(
            id=41,
            status="HELD",
            expires_at=timezone.now() + __import__("datetime").timedelta(days=1),
            position_id_id=case.position_instance_id,
            source_domain="HR14",
            source_business_id="CASE-OTHER",
        )
        reservation_objects.select_for_update.return_value.filter.return_value.first.return_value = reservation

        with self.assertRaises(AppointmentEffectError) as ctx:
            service._lock_capacity_receipt(case, reservation.id)

        self.assertEqual(ctx.exception.code, "APPOINTMENT_RESERVATION_OWNER_MISMATCH")
        position_objects.select_for_update.assert_not_called()

    @patch("hr_structure.models.HrPosition.objects")
    @patch("hr_structure.models.HrPositionReservation.objects")
    def test_capacity_receipt_accepts_current_case_id_as_owner(
        self, reservation_objects, position_objects
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, *_ = self._fixtures()
        reservation = SimpleNamespace(
            id=41,
            status="HELD",
            expires_at=timezone.now() + __import__("datetime").timedelta(days=1),
            position_id_id=case.position_instance_id,
            source_domain="HR14",
            source_business_id=str(case.id),
        )
        position = SimpleNamespace(id=case.position_instance_id)
        reservation_objects.select_for_update.return_value.filter.return_value.first.return_value = reservation
        position_objects.select_for_update.return_value.filter.return_value.first.return_value = position

        locked_reservation, locked_position = service._lock_capacity_receipt(case, reservation.id)

        self.assertIs(locked_reservation, reservation)
        self.assertIs(locked_position, position)

    @patch("hr_appointment.services.publicity_service.AppointmentPublicityService.assert_ready_for_effect")
    @patch("hr_structure.services.position.PositionService")
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_provider_failure_keeps_effect_pending_and_does_not_commit_reservation(
        self, assignment_service_cls, position_service_cls, publicity_gate
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, reservation, position, staff, relationship, publicity = self._fixtures()
        publicity_gate.return_value = publicity
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
        publicity_gate.assert_called_once_with(case.id)
        self.assertEqual(fact.status, PositionAppointmentFact.Status.EFFECT_PENDING)
        self.assertIn("HR03 write failed", fact.last_effect_error)
        self.assertEqual(case.status, AppointmentApplicationCase.Status.EFFECT_PENDING)
        position_service_cls.return_value.commit.assert_not_called()

    @patch("hr_appointment.services.publicity_service.AppointmentPublicityService.assert_ready_for_effect")
    @patch("hr_structure.services.position.PositionService")
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_success_requires_closed_publicity_then_provider_effect(
        self, assignment_service_cls, position_service_cls, publicity_gate
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, reservation, position, staff, relationship, publicity = self._fixtures()
        publicity_gate.return_value = publicity
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
        publicity_gate.assert_called_once_with(case.id)
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
        self.assertEqual(fact.effect_receipt_json["hr14PublicityId"], str(publicity.id))
        self.assertEqual(fact.effect_receipt_json["hr02ReservationId"], 41)
        self.assertEqual(fact.effect_receipt_json["hr02PositionId"], 31)

    @patch("hr_appointment.services.publicity_service.AppointmentPublicityService.assert_ready_for_effect")
    def test_publicity_gate_failure_prevents_pending_fact_creation(self, publicity_gate):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, *_ = self._fixtures()
        service._lock_case = MagicMock(return_value=case)
        service._get_or_create_pending_fact = MagicMock(return_value=fact)
        publicity_gate.side_effect = AppointmentPublicityError(
            "APPOINTMENT_PUBLICITY_NOT_CLOSED",
            "formal appointment effect requires a closed publicity record",
        )

        with self.assertRaises(AppointmentEffectError) as ctx:
            service.apply(
                case_id=case.id,
                appointment_no="APT-001",
                reservation_id=41,
                effective_from=date(2026, 9, 1),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_NOT_CLOSED")
        service._get_or_create_pending_fact.assert_not_called()

    @patch("hr_appointment.services.publicity_service.AppointmentPublicityService.assert_ready_for_effect")
    def test_already_effective_fact_still_requires_publicity_receipt_but_skips_providers(
        self, publicity_gate
    ):
        service = AppointmentEffectService(77, actor_user_id=9)
        case, fact, *_, publicity = self._fixtures()
        publicity_gate.return_value = publicity
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
        publicity_gate.assert_called_once_with(case.id)
        service._lock_capacity_receipt.assert_not_called()
