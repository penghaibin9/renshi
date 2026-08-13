import json
import uuid
from datetime import date, datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_appointment.population_api import freeze_population


class AppointmentPopulationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.batch_id = uuid.uuid4()

    def _request(self, payload):
        request = self.factory.post(
            "/api/v1/hr/appointments/batches/x/population/freeze/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = SimpleNamespace(id=9)
        return request

    @patch("hr_appointment.population_api.AppointmentPopulationService.freeze_from_hr03")
    @patch("hr_appointment.population_api.resolve_request_tenant", return_value=77)
    def test_freeze_population_uses_tenant_authority_and_returns_frozen_receipt(
        self, resolve_tenant, freeze
    ):
        snapshot = SimpleNamespace(
            id=uuid.uuid4(),
            batch_id=self.batch_id,
            as_of_date=date(2026, 8, 1),
            snapshot_at=datetime(2026, 8, 1, 8, 0, tzinfo=dt_timezone.utc),
            source_domain="HR03",
            source_version="hr03-employment-assignment-v1",
            member_count=20000,
            content_hash="a" * 64,
        )
        freeze.return_value = snapshot

        response = freeze_population(self._request({"asOfDate": "2026-08-01"}), self.batch_id)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["data"]["memberCount"], 20000)
        self.assertEqual(body["data"]["contentHash"], "a" * 64)
        self.assertEqual(response["Cache-Control"], "no-store")
        resolve_tenant.assert_called_once()
        freeze.assert_called_once_with(self.batch_id, as_of_date=date(2026, 8, 1))

    @patch("hr_appointment.population_api.resolve_request_tenant", return_value=77)
    def test_invalid_asof_is_rejected_before_service_call(self, resolve_tenant):
        response = freeze_population(self._request({"asOfDate": "not-a-date"}), self.batch_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_POPULATION_ASOF_INVALID", response.content)
