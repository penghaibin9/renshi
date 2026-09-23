import hashlib
import tempfile
from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from hr10_development.legacy.import_job import HrDevelopmentImportJob
from hr10_development.legacy.staging import HrDevelopmentStagingRow
from hr10_development.models import HrDevelopmentAuditEvent, HrDevelopmentPlan
from hr_staff.models import HrPerson, HrStaffMaster
from hr10_development.services.import_worker import (
    ImportExecutionError,
    ImportJobBusy,
    execute_import_job,
    run_import_job,
)


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
        person = HrPerson.objects.create(tenant_id=41, legal_name="导入测试教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=41, person_id=person, staff_no="IMPORT-123", legacy_employee_id=123
        )

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
            ["PLAN-001", "SCHOOL", "2026-01-01", "2026-12-31"],
            ["PLAN-002", "SCHOOL", "2026-12-31", "2026-01-01"],
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

    def test_individual_plan_import_resolves_hr03_uuid_and_executes(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "staff_master_id", "start_date", "end_date"],
            ["PLAN-INDIVIDUAL-001", "INDIVIDUAL", str(self.staff.id), "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)

        run_import_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, "PREVIEW")
        self.assertEqual(job.processed_rows, 1)
        self.assertEqual(job.error_rows, 0)
        staged = HrDevelopmentStagingRow.objects.get(import_job_id=job.id)
        self.assertEqual(staged.parsed_data["staff_master_uuid"], str(self.staff.id))
        self.assertEqual(staged.parsed_data["staff_master_legacy_id"], 123)

        execute_import_job(job.id, tenant_id=41)
        job.refresh_from_db()
        plan = HrDevelopmentPlan.objects.get(tenant_id=41, plan_no="PLAN-INDIVIDUAL-001")
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(plan.staff_master_uuid, self.staff.id)
        self.assertEqual(plan.staff_master_id, 123)

    def test_individual_plan_legacy_id_is_accepted_only_through_tenant_mapping(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "staff_master_id", "start_date", "end_date"],
            ["PLAN-INDIVIDUAL-LEGACY", "INDIVIDUAL", 123, "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        run_import_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.processed_rows, 1)
        staged = HrDevelopmentStagingRow.objects.get(import_job_id=job.id)
        self.assertEqual(staged.parsed_data["staff_master_uuid"], str(self.staff.id))

    def test_tampered_source_file_fails_closed(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-003", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload, file_hash="0" * 64)

        run_import_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.result_summary_json["errorCode"], "IMPORT_PARSE_FAILED")
        self.assertIn("SOURCE_FILE_HASH_MISMATCH", job.result_summary_json["error"])
        self.assertFalse(HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).exists())

    def test_active_parse_lease_blocks_duplicate_worker_and_expired_lease_is_reclaimed(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-LEASE", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        job.status = "PARSE"
        job.claim_token = "other-worker"
        job.lease_expires_at = timezone.now() + timedelta(minutes=5)
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["status", "claim_token", "lease_expires_at", "heartbeat_at", "updated_at"])

        run_import_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "PARSE")
        self.assertFalse(HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).exists())

        job.lease_expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["lease_expires_at", "updated_at"])
        run_import_job(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, "PREVIEW")
        self.assertEqual(job.result_summary_json.get("leaseTakeovers"), 1)
        self.assertEqual(HrDevelopmentStagingRow.objects.filter(import_job_id=job.id).count(), 1)
        self.assertEqual(job.claim_token, "")
        self.assertIsNone(job.lease_expires_at)

    def test_confirm_executes_authority_write_row_result_audit_and_replay_is_idempotent(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-EXEC-001", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        run_import_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "PREVIEW")

        result = execute_import_job(job.id, tenant_id=41, reason="test confirmation")
        result.refresh_from_db()

        self.assertEqual(result.status, "SUCCESS")
        self.assertTrue(result.result_summary_json["confirmed"])
        self.assertEqual(result.result_summary_json["executedRows"], 1)
        self.assertTrue(result.result_summary_json["allOrNothing"])
        target = HrDevelopmentPlan.objects.get(tenant_id=41, plan_no="PLAN-EXEC-001")
        staged = HrDevelopmentStagingRow.objects.get(import_job_id=job.id)
        self.assertEqual(staged.execution_status, "SUCCESS")
        self.assertEqual(staged.target_id, target.id)
        self.assertIsNotNone(staged.executed_at)
        self.assertEqual(
            HrDevelopmentAuditEvent.objects.filter(
                tenant_id=41, object_type="HrDevelopmentPlan", action="ImportRowExecuted"
            ).count(),
            1,
        )
        self.assertEqual(
            HrDevelopmentAuditEvent.objects.filter(
                tenant_id=41, object_type="HrDevelopmentImportJob", action="ImportConfirmedAndExecuted"
            ).count(),
            1,
        )

        replay = execute_import_job(job.id, tenant_id=41, reason="duplicate confirm")
        self.assertEqual(replay.status, "SUCCESS")
        self.assertEqual(HrDevelopmentPlan.objects.filter(tenant_id=41, plan_no="PLAN-EXEC-001").count(), 1)
        self.assertEqual(
            HrDevelopmentAuditEvent.objects.filter(
                tenant_id=41, object_type="HrDevelopmentImportJob", action="ImportConfirmedAndExecuted"
            ).count(),
            1,
        )

    def test_authority_conflict_after_preview_fails_closed_and_marks_row_failure(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-RACE-001", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        run_import_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "PREVIEW")

        HrDevelopmentPlan.objects.create(
            tenant_id=41,
            plan_no="PLAN-RACE-001",
            plan_type="SCHOOL",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )

        with self.assertRaises(ImportExecutionError) as captured:
            execute_import_job(job.id, tenant_id=41, reason="race conflict")
        self.assertEqual(captured.exception.code, "AUTHORITY_CONFLICT_AT_EXECUTION")

        job.refresh_from_db()
        staged = HrDevelopmentStagingRow.objects.get(import_job_id=job.id)
        self.assertEqual(job.status, "FAILED")
        self.assertTrue(job.result_summary_json["rolledBack"])
        self.assertEqual(staged.execution_status, "FAILED")
        self.assertIsNone(staged.target_id)
        self.assertEqual(HrDevelopmentPlan.objects.filter(tenant_id=41, plan_no="PLAN-RACE-001").count(), 1)
        self.assertEqual(
            HrDevelopmentAuditEvent.objects.filter(
                tenant_id=41, object_type="HrDevelopmentImportJob", action="ImportExecutionFailed"
            ).count(),
            1,
        )

    def test_execution_is_tenant_scoped(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-TENANT-001", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        run_import_job(job.id)

        with self.assertRaises(ImportExecutionError) as captured:
            execute_import_job(job.id, tenant_id=999)
        self.assertEqual(captured.exception.code, "IMPORT_NOT_FOUND")
        job.refresh_from_db()
        self.assertEqual(job.status, "PREVIEW")
        self.assertFalse(HrDevelopmentPlan.objects.filter(tenant_id=999, plan_no="PLAN-TENANT-001").exists())

    def test_active_execution_lease_rejects_duplicate_confirm(self):
        payload = _workbook_bytes([
            ["plan_no", "plan_type", "start_date", "end_date"],
            ["PLAN-BUSY-001", "SCHOOL", "2026-01-01", "2026-12-31"],
        ])
        job = self._job(payload)
        run_import_job(job.id)
        job.refresh_from_db()
        job.status = "EXECUTING"
        job.claim_token = "live-executor"
        job.lease_expires_at = timezone.now() + timedelta(minutes=5)
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["status", "claim_token", "lease_expires_at", "heartbeat_at", "updated_at"])

        with self.assertRaises(ImportJobBusy):
            execute_import_job(job.id, tenant_id=41)
        self.assertFalse(HrDevelopmentPlan.objects.filter(tenant_id=41, plan_no="PLAN-BUSY-001").exists())

