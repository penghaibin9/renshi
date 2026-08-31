"""第二轮复审修复测试：N1/N7 下载票据事务+归属、P1-3 乐观锁 VERSION_CONFLICT。"""

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_staff.constants import CorrectionEditMode
from hr_staff.models import HrFieldGovernancePolicy
from hr_staff.services.correction_service import (
    CorrectionService,
    CorrectionStateError,
)
from hr_staff.services.material_service import (
    MaterialAccessDenied,
    MaterialService,
)
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


class DownloadTicketConsumeTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")
        self.svc = MaterialService(TENANT, actor_user_id=1)

    def test_consume_works_within_transaction(self):
        """N1：consume 在事务内（select_for_update 不越界）；归属匹配可消费。"""
        material = self.svc.create_material(
            staff_id=self.staff, category_code="OTHER_HR", title="材料", storage_file_id="f"
        )
        ticket = self.svc.issue_download_ticket(
            staff_id=self.staff,
            material_id=material.id,
            purpose="x",
            permission_ok=True,
            sensitive_ok=True,
        )
        data = self.svc.consume_download_ticket(
            ticket["ticket"],
            expected_staff_id=self.staff.id,
            expected_material_id=material.id,
        )
        self.assertEqual(data["materialId"], str(material.id))

    def test_consume_wrong_staff_does_not_burn_ticket(self):
        """N7：URL 归属不符 → 拒绝且不烧票（可再用正确 URL 消费）。"""
        material = self.svc.create_material(
            staff_id=self.staff, category_code="OTHER_HR", title="材料", storage_file_id="f"
        )
        ticket = self.svc.issue_download_ticket(
            staff_id=self.staff,
            material_id=material.id,
            purpose="x",
            permission_ok=True,
            sensitive_ok=True,
        )
        other = make_staff(TENANT, make_person(TENANT, "李四"), "T999999")
        with self.assertRaises(MaterialAccessDenied):
            self.svc.consume_download_ticket(
                ticket["ticket"],
                expected_staff_id=other.id,
                expected_material_id=material.id,
            )
        # 票据未烧，正确归属仍可消费
        data = self.svc.consume_download_ticket(
            ticket["ticket"],
            expected_staff_id=self.staff.id,
            expected_material_id=material.id,
        )
        self.assertIsNotNone(data)


class CorrectionOptimisticLockTests(TestCase):
    def setUp(self):
        HrFieldGovernancePolicy.objects.update_or_create(
            tenant_id=TENANT,
            field_code="contact.work_email",
            defaults={
                "edit_mode": CorrectionEditMode.HR_DIRECT,
                "sensitivity_level": "RESTRICTED_HR",
                "required_evidence": False,
            },
        )
        self.staff = make_staff(TENANT, make_person(TENANT, "王五"), "T001239")
        self.svc = CorrectionService(TENANT, actor_user_id=1)

    def _approved_case(self):
        case = self.svc.create_case(
            staff_id=self.staff,
            reason="邮箱纠错",
            items=[{"field_code": "contact.work_email", "old_value_masked": "a@x.com", "new_value_masked": "b@x.com"}],
        )
        self.svc.submit(case.id)
        self.svc.review(case.id)
        self.svc.approve(case.id)
        case.refresh_from_db()
        return case

    def test_version_conflict_on_stale_version(self):
        """P1-3：expected_version 不匹配 → VERSION_CONFLICT。"""
        case = self._approved_case()
        with self.assertRaises(CorrectionStateError) as ctx:
            self.svc.apply(case.id, expected_version=case.version + 99)
        self.assertEqual(ctx.exception.code, "VERSION_CONFLICT")
        # 正确版本可应用
        case.refresh_from_db()
        applied = self.svc.apply(case.id, expected_version=case.version)
        applied.refresh_from_db()
        self.assertEqual(applied.status, "APPLIED")

    def test_apply_increments_version(self):
        case = self._approved_case()
        before = case.version
        applied = self.svc.apply(case.id)
        applied.refresh_from_db()
        self.assertEqual(applied.version, before + 1)
