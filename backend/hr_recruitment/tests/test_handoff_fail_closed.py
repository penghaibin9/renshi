from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_recruitment.constants import HandoffStatus
from hr_recruitment.services.handoff_service import HandoffService


class HandoffFailClosedTests(SimpleTestCase):
    @patch("hr_recruitment.services.audit_service.audit_event")
    @patch("hr_structure.models.HrPositionReservation")
    def test_reservation_invalid_after_hr05_case_keeps_handoff_failed_and_application_non_terminal(
        self,
        reservation_model,
        audit_event,
    ):
        reservation_model.Status.HELD = "HELD"
        reservation_model.objects.select_for_update.return_value.filter.return_value.first.return_value = (
            SimpleNamespace(status="RELEASED", expires_at=None)
        )
        consumer = MagicMock()
        consumer.handle.return_value = "case-123"

        app = SimpleNamespace(
            canonical_status="OFFER_ACCEPTED",
            version=3,
            save=MagicMock(),
        )
        proposed = SimpleNamespace(
            id="proposed-1",
            reservation_id=9,
            application_id=app,
        )
        handoff = SimpleNamespace(
            id="handoff-1",
            tenant_id=77,
            proposed_hire_id_id="proposed-1",
            proposed_hire_id=proposed,
            hr05_case_id="",
            status=HandoffStatus.FAILED,
            save=MagicMock(),
        )

        result = HandoffService(tenant_id=77)._complete_handoff(
            handoff,
            consumer,
            "idem-1",
        )

        consumer.handle.assert_called_once_with(
            tenant_id=77,
            proposed_hire_id="proposed-1",
            idempotency_key="idem-1",
        )
        self.assertEqual(result.status, HandoffStatus.FAILED)
        self.assertEqual(result.hr05_case_id, "case-123")
        app.save.assert_not_called()
        audit_event.assert_called_once()

    @patch("hr_recruitment.services.audit_service.audit_event")
    @patch("hr_recruitment.policies.state_machine.assert_transition")
    @patch("hr_recruitment.models.HrApplicationTransition")
    @patch("hr_structure.models.HrPositionReservation")
    @patch("hr_recruitment.integrations.hr02.Hr02ReservationProvider")
    def test_valid_handoff_keeps_reservation_held_for_hr05_activation(
        self,
        reservation_provider_cls,
        reservation_model,
        transition_model,
        assert_transition,
        audit_event,
    ):
        reservation_model.Status.HELD = "HELD"
        reservation_model.objects.select_for_update.return_value.filter.return_value.first.return_value = (
            SimpleNamespace(status="HELD", expires_at=None)
        )
        consumer = MagicMock()
        consumer.handle.return_value = "case-123"

        app = SimpleNamespace(
            canonical_status="OFFER_ACCEPTED",
            version=3,
            save=MagicMock(),
        )
        proposed = SimpleNamespace(
            id="proposed-1",
            reservation_id=9,
            application_id=app,
        )
        handoff = SimpleNamespace(
            id="handoff-1",
            tenant_id=77,
            proposed_hire_id_id="proposed-1",
            proposed_hire_id=proposed,
            hr05_case_id="",
            status=HandoffStatus.FAILED,
            save=MagicMock(),
        )

        result = HandoffService(tenant_id=77)._complete_handoff(
            handoff,
            consumer,
            "idem-1",
        )

        self.assertEqual(result.status, HandoffStatus.CREATED)
        self.assertEqual(result.hr05_case_id, "case-123")
        reservation_provider_cls.assert_not_called()
        assert_transition.assert_called_once()
        app.save.assert_called_once()
        transition_model.objects.create.assert_called_once()
        audit_event.assert_called_once()

    def test_service_requires_tenant(self):
        with self.assertRaises(Exception):
            HandoffService(tenant_id=0)
