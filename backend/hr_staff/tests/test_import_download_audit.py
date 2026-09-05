"""Download request attribution uses the real MySQL audit writer and URL graph."""
from unittest.mock import patch

from django.test import TestCase, override_settings

from hr_staff.models import HrStaffAuditEvent, HrStaffMaster
from hr_staff.tests.test_import_hr02 import ImportFixture
from hr_structure.tests.test_initial_setup import SETTINGS


@override_settings(**SETTINGS)
class StaffImportDownloadAuditTests(ImportFixture, TestCase):
    def test_each_error_download_keeps_a_distinct_server_generated_audit(self):
        browser = self.login(self.admin)
        uploaded = self.upload(browser, [self.row(), self.row("BAD-DOWNLOAD", legal_name="")])
        job_id = uploaded.json()["data"]["jobId"]
        path = "/api/v1/hr/staff/import/" + job_id + "/errors"
        first, second = browser.get(path), browser.get(path)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        ids = {first["X-HR-Request-ID"], second["X-HR-Request-ID"]}
        self.assertEqual(len(ids), 2)
        events = HrStaffAuditEvent.objects.filter(
            tenant_id=self.school.pk, action="StaffImportIssuesDownloaded", business_id=job_id,
        )
        self.assertEqual(events.count(), 2)
        self.assertEqual(set(events.values_list("request_id", flat=True)), ids)
        self.assertEqual(set(events.values_list("actor_user_id", flat=True)), {self.admin.pk})
        self.assertFalse(HrStaffMaster.objects.exists())

    def test_error_download_audit_failure_does_not_return_an_unlogged_workbook(self):
        browser = self.login(self.admin)
        uploaded = self.upload(browser, [self.row("BAD-AUDIT", legal_name="")])
        path = "/api/v1/hr/staff/import/" + uploaded.json()["data"]["jobId"] + "/errors"
        with patch("hr_staff.api.imports.write_audit_event", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                browser.get(path)
        self.assertFalse(HrStaffAuditEvent.objects.filter(action="StaffImportIssuesDownloaded").exists())
        self.assertFalse(HrStaffMaster.objects.exists())

