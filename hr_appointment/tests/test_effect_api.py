import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_appointment import api
from hr_appointment.services.effect_service import AppointmentEffectError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr14EffectApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    def _request(self, payload, *, permissions=()):
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/apply-effect/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = UserStub(permissions)
        return request

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_publicity_permission_cannot_execute_formal_effect(self, _allowed, _tenant):
        request = self._request(
            {
                "appointmentNo": "APT-2026-001",
                "reservationId": 41,
                "effectiveFrom": "2026-09-01",
            },
            permissions={api.PUBLICITY_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.EFFECT_PERMISSION.encode(), response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentEffectService")
    def test_effect_endpoint_passes_tenant_actor_and_authority_payload(
        self, service_cls, _allowed, _tenant
    ):
        fact_id = uuid.uuid4()
        fact = SimpleNamespace(
            id=fact_id,
            appointment_no="APT-2026-001",
            application_case_id=self.case_id,
            position_instance_id=31,
            effective_from=date(2026, 9, 1),
            status="EFFECTIVE",
            effect_receipt_json={"hr02ReservationId": 41},
        )
        service_cls.return_value.apply.return_value = SimpleNamespace(
            fact=fact,
            effective=True,
            error="",
        )
        request = self._request(
            {
                "appointmentNo": " APT-2026-001 ",
                "reservationId": "41",
                "effectiveFrom": "2026-09-01",
                "levelCode": " PRO_LEVEL_7 ",
            },
            permissions={api.EFFECT_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.apply.assert_called_once_with(
            case_id=self.case_id,
            appointment_no="APT-2026-001",
            reservation_id=41,
            effective_from=date(2026, 9, 1),
            level_code="PRO_LEVEL_7",
        )
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b'"effective": true', response.content)
        self.assertIn(b'"schemaVersion": "hr14.appointment-effect.1"', response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentEffectService")
    def test_provider_pending_result_returns_202_not_fake_success(
        self, service_cls, _allowed, _tenant
    ):
        fact = SimpleNamespace(
            id=uuid.uuid4(),
            appointment_no="APT-2026-002",
            application_case_id=self.case_id,
            position_instance_id=31,
            effective_from=date(2026, 9, 1),
            status="EFFECT_PENDING",
            effect_receipt_json={},
        )
        service_cls.return_value.apply.return_value = SimpleNamespace(
            fact=fact,
            effective=False,
            error="HR03 write failed",
        )
        request = self._request(
            {
                "appointmentNo": "APT-2026-002",
                "reservationId": 41,
                "effectiveFrom": "2026-09-01",
            },
            permissions={api.EFFECT_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 202)
        self.assertIn(b'"effective": false', response.content)
        self.assertIn(b"HR03 write failed", response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentEffectService")
    def test_effect_authority_conflict_maps_to_409(self, service_cls, _allowed, _tenant):
        service_cls.return_value.apply.side_effect = AppointmentEffectError(
            "APPOINTMENT_RESERVATION_OWNER_MISMATCH",
            "reservation is not owned by this appointment application",
        )
        request = self._request(
            {
                "appointmentNo": "APT-2026-003",
                "reservationId": 41,
                "effectiveFrom": "2026-09-01",
            },
            permissions={api.EFFECT_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_RESERVATION_OWNER_MISMATCH", response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_invalid_effect_date_and_reservation_id_are_rejected_before_service(
        self, _allowed, _tenant
    ):
        bad_date = self._request(
            {
                "appointmentNo": "APT-2026-004",
                "reservationId": 41,
                "effectiveFrom": "09/01/2026",
            },
            permissions={api.EFFECT_PERMISSION},
        )
        response = api.apply_effect(bad_date, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_DATE", response.content)

        bad_reservation = self._request(
            {
                "appointmentNo": "APT-2026-004",
                "reservationId": 0,
                "effectiveFrom": "2026-09-01",
            },
            permissions={api.EFFECT_PERMISSION},
        )
        response = api.apply_effect(bad_reservation, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_RESERVATION_ID", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/appointments/applications/{self.case_id}/apply-effect/"
        )
        request.user = UserStub({api.EFFECT_PERMISSION})

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 405)
