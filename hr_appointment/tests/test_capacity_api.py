import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_appointment import api, capacity_api
from hr_appointment.services.capacity_service import AppointmentCapacityError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr14CapacityApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    def _request(self, payload, *, permissions=()):
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/capacity-reservation/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = UserStub(permissions)
        return request

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_review_permission_cannot_hold_effect_capacity(self, _allowed, _tenant):
        request = self._request(
            {"quotaPoolId": str(uuid.uuid4())},
            permissions={api.REVIEW_PERMISSION},
        )

        response = capacity_api.prepare_capacity(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(api.EFFECT_PERMISSION.encode(), response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.capacity_api.AppointmentCapacityService")
    def test_prepare_capacity_returns_both_authority_receipts(
        self, service_cls, _allowed, _tenant
    ):
        quota_pool_id = str(uuid.uuid4())
        quota = SimpleNamespace(id=uuid.uuid4(), status="ACTIVE")
        position = SimpleNamespace(
            id=41,
            status="HELD",
            expires_at=timezone.now() + timedelta(days=7),
        )
        service_cls.return_value.prepare.return_value = SimpleNamespace(
            quota_reservation=quota,
            position_reservation=position,
        )
        expires_at = timezone.now().replace(microsecond=0) + timedelta(days=7)
        request = self._request(
            {
                "quotaPoolId": quota_pool_id,
                "expiresAt": expires_at.isoformat(),
            },
            permissions={api.EFFECT_PERMISSION},
        )

        response = capacity_api.prepare_capacity(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        kwargs = service_cls.return_value.prepare.call_args.kwargs
        self.assertEqual(kwargs["case_id"], self.case_id)
        self.assertEqual(kwargs["quota_pool_id"], quota_pool_id)
        self.assertEqual(kwargs["expires_at"], expires_at)
        self.assertIn(str(quota.id).encode(), response.content)
        self.assertIn(b'"hr02ReservationId": 41', response.content)
        self.assertIn(b'"schemaVersion": "hr14.appointment-capacity.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.capacity_api.AppointmentCapacityService")
    def test_capacity_exhaustion_maps_to_conflict(self, service_cls, _allowed, _tenant):
        service_cls.return_value.prepare.side_effect = AppointmentCapacityError(
            "APPOINTMENT_QUOTA_EXHAUSTED",
            "quota available=0, requested=1",
        )
        request = self._request(
            {"quotaPoolId": str(uuid.uuid4())},
            permissions={api.EFFECT_PERMISSION},
        )

        response = capacity_api.prepare_capacity(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_QUOTA_EXHAUSTED", response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_quota_pool_and_expiry_inputs_are_validated(self, _allowed, _tenant):
        missing_pool = self._request({}, permissions={api.EFFECT_PERMISSION})
        response = capacity_api.prepare_capacity(missing_pool, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_QUOTA_POOL_REQUIRED", response.content)

        bad_expiry = self._request(
            {
                "quotaPoolId": str(uuid.uuid4()),
                "expiresAt": "next Friday",
            },
            permissions={api.EFFECT_PERMISSION},
        )
        response = capacity_api.prepare_capacity(bad_expiry, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_DATETIME", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/appointments/applications/{self.case_id}/capacity-reservation/"
        )
        request.user = UserStub({api.EFFECT_PERMISSION})

        response = capacity_api.prepare_capacity(request, self.case_id)

        self.assertEqual(response.status_code, 405)
