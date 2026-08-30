import hashlib
import tempfile
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from openpyxl import Workbook

from hr10_development.legacy.import_job import HrDevelopmentImportJob
from hr10_development.legacy.staging import HrDevelopmentStagingRow
from hr10_development.services.import_worker import run_import_job


def _workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class ExcelImportPipelineTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.media_dir.cleanup()

    def _job(self, payload, *, file_hash=None):
        job = HrDevelopmentImportJob.objects.create(
            tenant_id=41,
            job_type="EXCEL_PLAN",
            file_name="plans.xlsx",
            file_hash=file_hash or hashlib.sha256(payload).hexdigest(),
            template_version="V1",
            status="PENDING",
        )
        job.source_file.save("plans.xlsx", ContentFile(payload), save=True)
        return job

    def test_real_xlsx_is_validated_staged_and_replayed_without_duplicate_rows(self):
        payload = _workbook_bytes([
            ["计划编号", "计划类型", "开始日期", "结束日期"],
            ["PLAN-001", "INDIVIDUAL", "2026-01-01", "2026-12-31"],
            ["PLAN-002", "INDIVIDUAL", "2026-12-31", "2026-01-01"],
        ])
        job = self._job(payload)

        run_import_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, "PREVIEW")
        self.assertEqual(job.total_rows, 2)
        self.assertEqual(job.processed_rows, 1)
        self.assertEqual(job.error_rows, 1)
        self.assertTrue(job.result_summary_json["replaySafe"])
        self.assertTrue(default_storage.exists(job.error_workbook_path))
        self.assertEqual(
            HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).count(),
            1,
        )
        staged = HrDevelopmentStagingRow.objects.get(import_job_id=job.id)
        self.assertEqual(staged.parsed_data["plan_no"], "PLAN-001")
        self.assertEqual(staged.target_model, "HrDevelopmentPlan")

        run_import_job(job.id)
        self.assertEqual(
            HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).count(),
            1,
        )

    def test_tampered_source_file_fails_closed(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-003", "INDIVIDUAL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload, file_hash="0" * 64)

        run_import_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.result_summary_json["errorCode"], "IMPORT_PARSE_FAILED")
        self.assertIn("SOURCE_FILE_HASH_MISMATCH", job.result_summary_json["error"])
        self.assertFalse(HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).exists())
