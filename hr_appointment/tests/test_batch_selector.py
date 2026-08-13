import uuid

from django.test import TestCase

from hr_appointment.models import AppointmentBatch
from hr_appointment.selectors import dashboard_snapshot


class AppointmentBatchSelectorTests(TestCase):
    def test_dashboard_exposes_real_competition_batches(self):
        batch = AppointmentBatch.objects.create(
            tenant_id=77,
            batch_no="APPT-2026-01",
            name="2026 年专业技术岗位竞聘",
            policy_version_id=uuid.uuid4(),
            business_type="COMPETITIVE_APPOINTMENT",
            status=AppointmentBatch.Status.APPLICATION_OPEN,
        )

        payload = dashboard_snapshot(77)

        self.assertEqual(payload["summary"]["competitionBatches"], 1)
        self.assertTrue(payload["capabilities"]["competition"])
        self.assertEqual(len(payload["recentBatches"]), 1)
        self.assertEqual(payload["recentBatches"][0]["id"], batch.id)
        self.assertEqual(payload["recentBatches"][0]["batch_no"], "APPT-2026-01")
        self.assertEqual(
            payload["recentBatches"][0]["status"],
            AppointmentBatch.Status.APPLICATION_OPEN,
        )

    def test_dashboard_keeps_batches_tenant_scoped(self):
        AppointmentBatch.objects.create(
            tenant_id=77,
            batch_no="APPT-77",
            name="本校批次",
            policy_version_id=uuid.uuid4(),
        )
        AppointmentBatch.objects.create(
            tenant_id=88,
            batch_no="APPT-88",
            name="外校批次",
            policy_version_id=uuid.uuid4(),
        )

        payload = dashboard_snapshot(77)

        self.assertEqual(payload["summary"]["competitionBatches"], 1)
        self.assertEqual(
            [row["batch_no"] for row in payload["recentBatches"]],
            ["APPT-77"],
        )
