from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_recruitment.constants import HandoffStatus
from hr_recruitment.services.handoff_service import HandoffService


class HandoffFailClosedTests(SimpleTestCase):
    @patch("hr_recruitment.services.audit_service.audit_event")
    @patch("hr_recruitment.integrations.hr02.Hr02ReservationProvider")
    def test_reservation_commit_failure_keeps_handoff_failed_and_application_non_terminal(
        self,
        reservation_provider_cls,
        audit_event,
    ):
        reservation_provider_cls.return_value.commit.side_effect = RuntimeError("hr02 down")
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
        reservation_provider_cls.assert_called_once_with(tenant_id=77, actor="")
        reservation_provider_cls.return_value.commit.assert_called_once_with(9)
        self.assertEqual(result.status, HandoffStatus.FAILED)
        self.assertEqual(result.hr05_case_id, "case-123")
        app.save.assert_not_called()
        audit_event.assert_called_once()

    def test_service_requires_tenant(self):
        with self.assertRaises(Exception):
            HandoffService(tenant_id=0)
