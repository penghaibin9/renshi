import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_appointment import decision_api
from hr_appointment.services.decision_service import AppointmentDecisionError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def has_perm(self, code):
        return code == decision_api.DECISION_PERMISSION


class AppointmentCollectiveDecisionApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    @patch("hr_appointment.decision_api.resolve_request_tenant", return_value=77)
    @patch("hr_appointment.decision_api.AppointmentDecisionService")
    def test_record_requires_dedicated_decision_permission_and_forwards_human_authority(
        self, service_cls, tenant_resolver
    ):
        now = timezone.now()
        decision = SimpleNamespace(
            id=uuid.uuid4(),
            decision_no="DEC-001",
            application_case_id=self.case_id,
            publicity_id=uuid.uuid4(),
            batch_no="B-2026",
            person_id=uuid.uuid4(),
            position_instance_id=1001,
            outcome="APPROVED",
            authority_ref="校长办公会纪要〔2026〕12号",
            decision_reason="集体审定通过",
            decided_at=now,
        )
        service_cls.return_value.record.return_value = (decision, True)
        request = self.factory.post(
            "/collective-decision/",
            data=json.dumps(
                {
                    "decisionNo": decision.decision_no,
                    "outcome": "APPROVED",
                    "authorityRef": decision.authority_ref,
                    "decisionReason": decision.decision_reason,
                    "evidenceSnapshot": {"meetingRef": "2026-12"},
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = decision_api.record_collective_decision(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=decision_api.DECISION_PERMISSION
        )
        kwargs = service_cls.return_value.record.call_args.kwargs
        self.assertEqual(kwargs["case_id"], self.case_id)
        self.assertEqual(kwargs["outcome"], "APPROVED")
        self.assertEqual(kwargs["authority_ref"], decision.authority_ref)
        self.assertIn(b'"schemaVersion": "hr14.collective-decision.1"', response.content)

    @patch("hr_appointment.decision_api.resolve_request_tenant", return_value=77)
    @patch("hr_appointment.decision_api.AppointmentDecisionService")
    def test_state_conflict_maps_to_409(self, service_cls, tenant_resolver):
        service_cls.return_value.record.side_effect = AppointmentDecisionError(
            "APPOINTMENT_DECISION_ALREADY_RECORDED",
            "latest publicity already has a collective decision fact",
        )
        request = self.factory.post(
            "/collective-decision/",
            data=json.dumps(
                {
                    "decisionNo": "DEC-002",
                    "outcome": "APPROVED",
                    "authorityRef": "校长办公会纪要",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = decision_api.record_collective_decision(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_DECISION_ALREADY_RECORDED", response.content)
