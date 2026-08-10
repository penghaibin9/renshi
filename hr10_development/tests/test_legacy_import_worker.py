from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr10_development.services.import_worker import _parse_legacy_employee


class LegacyImportWorkerTests(SimpleTestCase):
    @patch("hr10_development.legacy.staging.HrDevelopmentStagingRow.objects")
    @patch("employee.models.Employee.objects")
    def test_legacy_employee_parse_is_tenant_scoped_and_stages_unverified_only(
        self,
        employee_objects,
        staging_objects,
    ):
        employee = SimpleNamespace(id=11, qualification="企业实践证书")
        values_qs = MagicMock()
        values_qs.__iter__.return_value = iter([employee])
        ordered_qs = MagicMock()
        ordered_qs.__getitem__.return_value = values_qs
        employee_objects.filter.return_value.order_by.return_value = ordered_qs
        staging_objects.get_or_create.return_value = (MagicMock(), True)

        job = MagicMock()
        job.id = 99
        job.tenant_id = 77

        _parse_legacy_employee(job)

        employee_objects.filter.assert_called_once_with(
            employee_work_info__company_id_id=77,
            is_active=True,
        )
        ordered_qs.__getitem__.assert_called_once_with(slice(None, 5000, None))
        staging_objects.get_or_create.assert_called_once_with(
            tenant_id=77,
            import_job_id=99,
            source_system="LEGACY_EMPLOYEE",
            source_table="Employee",
            source_field="qualification",
            source_object_id="11",
            defaults={
                "raw_text": "企业实践证书",
                "migration_trust_level": "UNKNOWN",
                "verification_status": "PENDING",
                "target_model": "",
            },
        )
        self.assertEqual(job.processed_rows, 1)
        self.assertFalse(job.result_summary_json["authority"])
        self.assertEqual(job.result_summary_json["trustLevel"], "UNKNOWN")

    @patch("hr10_development.legacy.staging.HrDevelopmentStagingRow.objects")
    @patch("employee.models.Employee.objects")
    def test_worker_retry_does_not_double_count_existing_staging_row(
        self,
        employee_objects,
        staging_objects,
    ):
        employee = SimpleNamespace(id=11, qualification="企业实践证书")
        values_qs = MagicMock()
        values_qs.__iter__.return_value = iter([employee])
        ordered_qs = MagicMock()
        ordered_qs.__getitem__.return_value = values_qs
        employee_objects.filter.return_value.order_by.return_value = ordered_qs
        staging_objects.get_or_create.return_value = (MagicMock(), False)

        job = MagicMock(id=99, tenant_id=77)
        _parse_legacy_employee(job)

        self.assertEqual(job.processed_rows, 0)
        self.assertEqual(job.result_summary_json["stagedRows"], 0)
