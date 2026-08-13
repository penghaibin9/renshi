import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from hr_appointment import term_api
from hr_appointment.api import HrAppointmentAccessError


class AppointmentTermApiContractTests(SimpleTestCase):
    def _request(self, body=None):
        request = RequestFactory().post(
            "/api/v1/hr/appointments/term-contract-test/",
            data=json.dumps(body or {}),
            content_type="application/json",
        )
        request.user = SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)
        return request

    def test_term_routes_are_canonical(self):
        fact_id = uuid.uuid4()
        term_id = uuid.uuid4()
        renewal_id = uuid.uuid4()
        change_id = uuid.uuid4()
        expected = {
            "hr_appointment_api:term-register": (
                {"fact_id": fact_id},
                f"/api/v1/hr/appointments/appointment-facts/{fact_id}/term/",
            ),
            "hr_appointment_api:term-mark-expiring": (
                {"term_id": term_id},
                f"/api/v1/hr/appointments/terms/{term_id}/expiring/",
            ),
            "hr_appointment_api:term-mark-expired": (
                {"term_id": term_id},
                f"/api/v1/hr/appointments/terms/{term_id}/expired/",
            ),
            "hr_appointment_api:renewal-open": (
                {"term_id": term_id},
                f"/api/v1/hr/appointments/terms/{term_id}/renewals/",
            ),
            "hr_appointment_api:renewal-decision": (
                {"renewal_id": renewal_id},
                f"/api/v1/hr/appointments/renewals/{renewal_id}/decision/",
            ),
            "hr_appointment_api:renewal-effect-apply": (
                {"renewal_id": renewal_id},
                f"/api/v1/hr/appointments/renewals/{renewal_id}/apply-effect/",
            ),
            "hr_appointment_api:term-change-open": (
                {"term_id": term_id},
                f"/api/v1/hr/appointments/terms/{term_id}/changes/",
            ),
            "hr_appointment_api:term-change-decision": (
                {"change_id": change_id},
                f"/api/v1/hr/appointments/term-changes/{change_id}/decision/",
            ),
            "hr_appointment_api:term-change-effect-apply": (
                {"change_id": change_id},
                f"/api/v1/hr/appointments/term-changes/{change_id}/apply-effect/",
            ),
        }
        for name, (kwargs, path) in expected.items():
            self.assertEqual(reverse(name, kwargs=kwargs), path)
            self.assertEqual(resolve(path).view_name, name)

    @patch("hr_appointment.term_api.resolve_request_tenant")
    def test_term_write_requires_dedicated_permission(self, resolve_tenant):
        request = self._request()
        resolve_tenant.side_effect = HrAppointmentAccessError(
            "PERMISSION_DENIED", "missing term permission"
        )
        response = term_api.mark_expiring(request, uuid.uuid4())
        self.assertEqual(response.status_code, 403)
        resolve_tenant.assert_called_once_with(
            request,
            required_permission="hr.appointment.term",
        )

    @patch("hr_appointment.term_api.AppointmentTermService")
    @patch("hr_appointment.term_api.resolve_request_tenant", return_value=77)
    def test_renewal_approval_never_claims_effect_applied(
        self, resolve_tenant, service_cls
    ):
        renewal = SimpleNamespace(
            id=uuid.uuid4(),
            renewal_no="REN-001",
            status="APPROVED",
        )
        term = SimpleNamespace(status="RENEWAL_IN_PROGRESS")
        service_cls.return_value.decide_renewal.return_value = SimpleNamespace(
            renewal=renewal,
            term=term,
        )
        response = term_api.decide_renewal(
            self._request(
                {"outcome": "APPROVED", "decisionSnapshot": {"decision": "renew"}}
            ),
            renewal.id,
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertFalse(payload["data"]["termEffectApplied"])
        self.assertEqual(payload["data"]["status"], "APPROVED")

    @patch("hr_appointment.term_api.AppointmentTermService")
    @patch("hr_appointment.term_api.resolve_request_tenant", return_value=77)
    def test_change_approval_never_claims_effect_applied(
        self, resolve_tenant, service_cls
    ):
        change = SimpleNamespace(id=uuid.uuid4(), change_no="CHG-001", status="APPROVED")
        term = SimpleNamespace(status="ACTIVE")
        service_cls.return_value.decide_change.return_value = SimpleNamespace(
            change=change,
            term=term,
        )
        response = term_api.decide_change(
            self._request({"outcome": "APPROVED", "decisionSnapshot": {"decision": "ok"}}),
            change.id,
        )
        payload = json.loads(response.content)
        self.assertFalse(payload["data"]["termEffectApplied"])
        self.assertEqual(payload["data"]["status"], "APPROVED")

    @patch("hr_appointment.term_api.AppointmentTermService")
    @patch("hr_appointment.term_api.resolve_request_tenant", return_value=77)
    def test_register_term_parses_dates_and_returns_201(
        self, resolve_tenant, service_cls
    ):
        fact_id = uuid.uuid4()
        term = SimpleNamespace(
            id=uuid.uuid4(),
            term_no="TERM-001",
            appointment_fact_id=fact_id,
            effective_from=date(2026, 9, 1),
            effective_to=date(2029, 9, 1),
            renewal_due_at=date(2029, 6, 1),
            status="ACTIVE",
        )
        service_cls.return_value.register_from_effective_fact.return_value = term
        response = term_api.register_term(
            self._request(
                {
                    "termNo": "TERM-001",
                    "effectiveTo": "2029-09-01",
                    "renewalDueAt": "2029-06-01",
                }
            ),
            fact_id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        kwargs = service_cls.return_value.register_from_effective_fact.call_args.kwargs
        self.assertEqual(kwargs["effective_to"], date(2029, 9, 1))
        self.assertEqual(kwargs["renewal_due_at"], date(2029, 6, 1))
