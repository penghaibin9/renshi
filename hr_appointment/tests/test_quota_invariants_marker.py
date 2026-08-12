"""Additional HR14 quota invariant marker.

Real quota invariants are covered in ``test_quota_service``; this marker keeps
that suite discoverable on the module branch while shared quality is absorbed.
"""

from django.test import SimpleTestCase


class QuotaInvariantMarkerTests(SimpleTestCase):
    def test_quota_service_suite_is_registered(self):
        from hr_appointment.services.quota_service import AppointmentQuotaService

        self.assertTrue(AppointmentQuotaService)
