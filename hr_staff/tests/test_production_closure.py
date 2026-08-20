"""Focused contracts for the no-Actions HR03 production-closure fixes."""

from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from hr_staff.constants import ImportJobStatus, StaffScopeType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import HrExportJob
from hr_staff.selectors.staff_list import StaffListSelector
from hr_staff.services.export_service import (
    ExportContentStore,
    ExportContentUnavailable,
    ExportPolicyDenied,
    ExportService,
)
from hr_staff.services.import_service import ImportService
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


class ImportProductionClosureTests(TestCase):
    def test_commit_injects_job_scoped_stable_source_identity(self):
        service = ImportService(TENANT, actor_user_id=7)
        job = service.create_job(template_key="staff_master")
        service.parse_rows(job, [{"legal_name": "导入测试", "staff_no": "IMP-001"}])
        service.validate_rows(job, row_validator=lambda row: {})
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
        service = ImportService(TENANT, actor_user_id=7)
        job = service.create_job(template_key="staff_master")
        service.parse_rows(job, [{"legal_name": "导入测试", "staff_no": "IMP-002"}])
        service.validate_rows(job, row_validator=lambda row: {})
        calls = []

        def applier(row, checkpoint):
            calls.append(row["_import_row_no"])

        service.commit(job, applier)
        service.commit(job, applier)
        self.assertEqual(calls, [2])
