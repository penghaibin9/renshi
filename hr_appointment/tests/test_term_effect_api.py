import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_appointment import term_effect_api
from hr_appointment.api import HrAppointmentAccessError
from hr_appointment.services.term_effect_service import AppointmentTermEffectError


class AppointmentTermEffectApiTests(SimpleTestCase):
    def _request(self, body=None):
        request = RequestFactory().post(
            "/api/v1/hr/appointments/term-effect-contract-test/",
            data=json.dumps(body or {}),
            content_type="application/json",
        )
        request.user = SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)
        return request

    @patch("hr_appointment.term_effect_api.resolve_request_tenant")
    def test_effect_requires_term_permission(self, resolve_tenant):
        request = self._request()
        resolve_tenant.side_effect = HrAppointmentAccessError(
            "PERMISSION_DENIED", "missing term permission"
        )
        response = term_effect_api.apply_renewal_effect(request, uuid.uuid4())
        self.assertEqual(response.status_code, 403)
        resolve_tenant.assert_called_once_with(
            request,
            required_permission="hr.appointment.term",
        )

    @patch("hr_appointment.term_effect_api.AppointmentTermEffectService")
    @patch("hr_appointment.term_effect_api.resolve_request_tenant", return_value=77)
    def test_renewal_effect_returns_real_successor_ids(self, resolve_tenant, service_cls):
        renewal_id = uuid.uuid4()
        fact = SimpleNamespace(
            id=uuid.uuid4(),
            appointment_no="APT-REN-001",
            status="EFFECTIVE",
            effect_receipt_json={"hr03Effect": "VERIFIED_UNCHANGED_POSITION"},
        )
        term = SimpleNamespace(
            id=uuid.uuid4(),
            term_no="TERM-REN-001",
            status="ACTIVE",
        )
        service_cls.return_value.apply_renewal.return_value = SimpleNamespace(
            fact=fact,
            term=term,
            applied=True,
            error="",
        )
        response = term_effect_api.apply_renewal_effect(
            self._request(
                {
                    "appointmentNo": "APT-REN-001",
                    "successorTermNo": "TERM-REN-001",
                    "renewalDueAt": "2032-06-01",
                }
            ),
            renewal_id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        payload = json.loads(response.content)
        self.assertTrue(payload["data"]["applied"])
        self.assertEqual(payload["data"]["successorFactId"], str(fact.id))
        self.assertEqual(payload["data"]["successorTermId"], str(term.id))
        service_cls.return_value.apply_renewal.assert_called_once_with(
            renewal_id,
            appointment_no="APT-REN-001",
            successor_term_no="TERM-REN-001",
            renewal_due_at=date(2032, 6, 1),
        )

    @patch("hr_appointment.term_effect_api.AppointmentTermEffectService")
    @patch("hr_appointment.term_effect_api.resolve_request_tenant", return_value=77)
    def test_provider_failure_is_503_and_never_claims_applied(
        self, resolve_tenant, service_cls
    ):
        fact = SimpleNamespace(
            id=uuid.uuid4(),
            appointment_no="APT-XFER-001",
            status="EFFECT_PENDING",
        )
        service_cls.return_value.apply_change.return_value = SimpleNamespace(
            fact=fact,
            term=None,
            applied=False,
            error="HR03 temporary failure",
        )
        response = term_effect_api.apply_change_effect(
            self._request(
                {
                    "appointmentNo": "APT-XFER-001",
                    "successorTermNo": "TERM-XFER-001",
                    "reservationId": 501,
                }
            ),
            uuid.uuid4(),
        )
        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.content)
        self.assertFalse(payload["data"]["applied"])
        self.assertTrue(payload["error"]["retryable"])
        self.assertEqual(payload["data"]["appointmentStatus"], "EFFECT_PENDING")

    @patch("hr_appointment.term_effect_api.AppointmentTermEffectService")
    @patch("hr_appointment.term_effect_api.resolve_request_tenant", return_value=77)
    def test_correction_without_authority_maps_to_conflict(
        self, resolve_tenant, service_cls
    ):
        service_cls.return_value.apply_change.side_effect = AppointmentTermEffectError(
            "APPOINTMENT_CORRECTION_EFFECT_AUTHORITY_REQUIRED",
            "formal correction requires an explicit correction authority payload",
        )
        response = term_effect_api.apply_change_effect(
            self._request(
                {
                    "appointmentNo": "APT-CORRECT-001",
                    "successorTermNo": "TERM-CORRECT-001",
                }
            ),
            uuid.uuid4(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn(
            b"APPOINTMENT_CORRECTION_EFFECT_AUTHORITY_REQUIRED",
            response.content,
        )
