"""Focused contracts for the no-Actions HR03 production-closure fixes."""

from datetime import timedelta
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.utils import timezone

from hr_staff.constants import ImportJobStatus, StaffScopeType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import HrExportJob
from hr_staff.selectors.staff_list import StaffListSelector
from hr_staff.services.export_service import (
    ExportContentStore,
    ExportContentUnavailable,
    ExportPolicyDenied,
    ExportService,
    _safe_csv_cell,
)
from hr_staff.services.import_service import ImportService, ImportStateConflict
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


class StaffScopeFailClosedTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "范围测试"), "SCOPE-001")

    def _count(self, scope):
        context = HrStaffRequestContext(tenant_id=TENANT, scope=scope)
        selector = StaffListSelector(context)
        return selector.apply_scope(selector.base_qs()).count()

    def test_self_without_staff_identity_is_empty(self):
        self.assertEqual(
            self._count(HrStaffScope(scope_type=StaffScopeType.SELF)),
            0,
        )

    def test_explicit_set_without_ids_is_empty(self):
        self.assertEqual(
            self._count(HrStaffScope(scope_type=StaffScopeType.EXPLICIT_STAFF_SET)),
            0,
        )

    def test_assignment_without_ids_is_empty(self):
        self.assertEqual(
            self._count(HrStaffScope(scope_type=StaffScopeType.ASSIGNMENT)),
            0,
        )

    def test_org_scope_without_org_id_is_empty(self):
        self.assertEqual(
            self._count(HrStaffScope(scope_type=StaffScopeType.DEPARTMENT)),
            0,
        )


class ExportProductionClosureTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.override.enable()
        ExportContentStore.clear()
        self.staff = make_staff(TENANT, make_person(TENANT, "导出测试"), "EXP-001")
        self.context = HrStaffRequestContext(
            tenant_id=TENANT,
            user_id=11,
            scope=HrStaffScope(
                scope_type=StaffScopeType.EXPLICIT_STAFF_SET,
                staff_ids=frozenset({str(self.staff.id)}),
            ),
        )

    def tearDown(self):
        ExportContentStore.clear()
        self.override.disable()
        self.temp_media.cleanup()

    def _create(self):
        return ExportService(TENANT, actor_user_id=11, context=self.context).create_export(
            purpose="生产收口测试",
            staff_ids=[str(self.staff.id)],
            fields=["staff_no", "legal_name"],
            has_export_sensitive=False,
        )

    def test_export_content_survives_service_instance(self):
        job = self._create()
        self.assertTrue(job.file_ref)
        content = ExportService(
            TENANT, actor_user_id=11, context=self.context
        ).consume_download(job.id, job.download_token)["content"]
        self.assertIn("EXP-001", content)

    def test_download_is_bound_to_requester(self):
        job = self._create()
        with self.assertRaises(ExportPolicyDenied):
            ExportService(
                TENANT, actor_user_id=22, context=self.context
            ).consume_download(job.id, job.download_token)
        job.refresh_from_db()
        self.assertIsNone(job.consumed_at)

    def test_missing_storage_does_not_consume_ticket(self):
        job = self._create()
        ExportContentStore.delete(job.file_ref)
        with self.assertRaises(ExportContentUnavailable):
            ExportService(
                TENANT, actor_user_id=11, context=self.context
            ).consume_download(job.id, job.download_token)
        job.refresh_from_db()
        self.assertIsNone(job.consumed_at)
        self.assertEqual(job.status, HrExportJob.Status.FAILED)

    def test_csv_formula_payloads_are_forced_to_text(self):
        self.assertEqual(
            _safe_csv_cell('=HYPERLINK("https://bad")'),
            "'=HYPERLINK(\"https://bad\")",
        )
        self.assertEqual(_safe_csv_cell("  +1+1"), "'  +1+1")
        self.assertEqual(_safe_csv_cell("@SUM(A1:A2)"), "'@SUM(A1:A2)")
        self.assertEqual(_safe_csv_cell("normal-name"), "normal-name")


class ImportProductionClosureTests(TestCase):
    def _ready_job(self, staff_no="IMP-001"):
        service = ImportService(TENANT, actor_user_id=7)
        job = service.create_job(template_key="staff_master")
        service.parse_rows(job, [{"legal_name": "导入测试", "staff_no": staff_no}])
        service.validate_rows(job, row_validator=lambda row: {})
        return service, job

    def test_commit_injects_job_scoped_stable_source_identity(self):
        service, job = self._ready_job()
        seen = []

        def applier(row, checkpoint):
            seen.append((row["_import_job_id"], row["_import_row_no"]))

        result = service.commit(job, applier)
        self.assertEqual(result["committed"], 1)
        self.assertEqual(seen, [(str(job.id), 2)])
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.COMPLETED)
        self.assertIsNotNone(job.committed_at)

    def test_terminal_job_is_not_executed_twice(self):
        service, job = self._ready_job("IMP-002")
        calls = []

        def applier(row, checkpoint):
            calls.append(row["_import_row_no"])

        service.commit(job, applier)
        service.commit(job, applier)
        self.assertEqual(calls, [2])

    def test_active_commit_lease_blocks_second_executor(self):
        service, job = self._ready_job("IMP-003")
        now = timezone.now()
        job.status = ImportJobStatus.COMMITTING
        job.checkpoint = {
            "commit_started_at": now.isoformat(),
            "commit_heartbeat_at": now.isoformat(),
        }
        job.save(update_fields=["status", "checkpoint"])

        with self.assertRaises(ImportStateConflict):
            service.commit(job, lambda row, checkpoint: None)

    def test_stale_commit_lease_resumes_only_uncommitted_rows(self):
        service, job = self._ready_job("IMP-004")
        row = job.rows.get(row_no=2)
        old = timezone.now() - timedelta(hours=1)
        job.status = ImportJobStatus.COMMITTING
        job.checkpoint = {
            "commit_started_at": old.isoformat(),
            "commit_heartbeat_at": old.isoformat(),
        }
        job.save(update_fields=["status", "checkpoint"])
        calls = []

        result = service.commit(job, lambda payload, checkpoint: calls.append(payload["_import_row_no"]))

        self.assertEqual(result["committed"], 1)
        self.assertEqual(calls, [2])
        row.refresh_from_db()
        self.assertEqual(row.commit_status, "COMMITTED")
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.COMPLETED)
        self.assertEqual(job.checkpoint.get("resume_count"), 1)
        self.assertNotIn("commit_heartbeat_at", job.checkpoint)

    def test_parse_rows_cannot_be_replayed_into_same_job(self):
        service = ImportService(TENANT, actor_user_id=7)
        job = service.create_job(template_key="staff_master")
        service.parse_rows(job, [{"legal_name": "首次解析"}])
        with self.assertRaises(ImportStateConflict):
            service.parse_rows(job, [{"legal_name": "重复解析"}])
        self.assertEqual(job.rows.count(), 1)
