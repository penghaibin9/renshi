"""第四轮修复：导出服务 + 导入真实 applier 测试。"""

import csv
import io
from datetime import date
from unittest import mock

from django.test import TestCase

from hr_staff.models import HrExportJob, HrStaffAuditEvent
from hr_staff.services.export_service import (
    ExportContentStore,
    ExportPolicyDenied,
    ExportService,
)
from hr_staff.services.import_service import (
    ImportService,
    StaffMasterRowApplier,
)
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


class ExportServiceTests(TestCase):
    def setUp(self):
        ExportContentStore.clear()
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")
        self.svc = ExportService(TENANT, actor_user_id=1)

    def test_export_requires_purpose(self):
        with self.assertRaises(ExportPolicyDenied):
            self.svc.create_export(
                purpose="", staff_ids=[self.staff.id], fields=["staff_no"], has_export_sensitive=False
            )

    def test_export_removes_sensitive_fields_without_permission(self):
        job = self.svc.create_export(
            purpose="年报",
            staff_ids=[self.staff.id],
            fields=["staff_no", "work_phone"],
            has_export_sensitive=False,
        )
        self.assertNotIn("work_phone", job.fields_json)
        self.assertIn("staff_no", job.fields_json)
        # 审计
        self.assertTrue(
            HrStaffAuditEvent.objects.filter(
                tenant_id=TENANT, action="StaffExportCreated"
            ).exists()
        )

    def test_export_keeps_sensitive_with_permission(self):
        job = self.svc.create_export(
            purpose="薪酬核对",
            staff_ids=[self.staff.id],
            fields=["staff_no", "work_phone"],
            has_export_sensitive=True,
        )
        self.assertIn("work_phone", job.fields_json)

    def test_download_single_use_ticket(self):
        job = self.svc.create_export(
            purpose="年报", staff_ids=[self.staff.id], fields=["staff_no"], has_export_sensitive=False
        )
        data = self.svc.consume_download(job.id, job.download_token)
        self.assertIn("T001238", data["content"])
        # 一次性
        with self.assertRaises(ExportPolicyDenied):
            self.svc.consume_download(job.id, job.download_token)


class ImportApplierTests(TestCase):
    def test_staff_master_row_applier_creates_person_staff_employment(self):
        """P1-i：真实 applier 一行创建 Person+Staff+Relationship+Assignment（原子）。"""
        from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment

        applier = StaffMasterRowApplier(TENANT, actor_user_id=1)
        applier(
            {
                "staff_no": "T500001",
                "legal_name": "钱七",
                "effective_from": "2024-09-01",
                "legacy_department_id": "7",
            },
            {},
        )
        staff = HrStaffMaster.objects.get(tenant_id=TENANT, staff_no="T500001")
        self.assertEqual(staff.person_id.legal_name, "钱七")
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(tenant_id=TENANT, staff_id=staff).count(), 1
        )
        assignment = HrStaffAssignment.objects.filter(
            tenant_id=TENANT, employment_relationship_id__staff_id=staff
        ).first()
        self.assertEqual(assignment.legacy_department_id, 7)

    def test_import_service_commit_with_real_applier(self):
        """P1-i：commit 走真实 applier，成功/失败行精确统计。"""
        svc = ImportService(TENANT, actor_user_id=1)
        job = svc.create_job(template_key="staff_master")
        svc.parse_rows(
            job,
            [
                {"staff_no": "T600001", "legal_name": "孙八", "effective_from": "2024-09-01"},
                {"legal_name": ""},  # 缺姓名 → 校验失败
            ],
        )
        svc.validate_rows(job, row_validator=lambda r: {"legal_name": "必填"} if not r.get("legal_name") else {})
        result = svc.commit(job, StaffMasterRowApplier(TENANT, actor_user_id=1))
        self.assertEqual(result["committed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(
            HrStaffMaster.objects.filter(tenant_id=TENANT, staff_no="T600001").exists()
        )
