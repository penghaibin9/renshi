"""S3 · AssignmentService 不变量测试：并发 PRIMARY、重叠、跨租户、主岗切换原子。"""

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.models import HrStaffAssignment
from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
OTHER_TENANT = 2
FIXTURE_SOURCE = "AUTHORIZED_CORRECTION"


class AssignmentInvariantTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "李老师")
        self.staff = make_staff(TENANT, self.person, "T000099")
        self.computer = make_org(TENANT, "JSXY", "计算机学院", date(2024, 1, 1))
        self.ai = make_org(TENANT, "AIXY", "人工智能学院", date(2024, 1, 1))
        self.other_org = make_org(OTHER_TENANT, "BXY", "B校学院", date(2024, 1, 1))
        self.emp = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        self.service = AssignmentService(TENANT)

    def test_cross_tenant_organization_rejected(self):
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2024, 9, 1),
                organization_id=self.other_org,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "CROSS_TENANT_REFERENCE")

    def test_primary_without_org_or_legacy_rejected(self):
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2024, 9, 1),
                organization_id=None,
                legacy_department_id=None,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "ORG_MAPPING_MISSING")

    def test_legacy_preview_mode_allowed(self):
        assignment = self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=None,
            legacy_department_id=7,
            source_business_type=FIXTURE_SOURCE,
        )
        self.assertEqual(assignment.legacy_department_id, 7)

    def test_dual_open_primary_rejected_by_policy(self):
        self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
            source_business_type=FIXTURE_SOURCE,
        )
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2025, 1, 1),
                organization_id=self.ai,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_OVERLAP")

    def test_db_backstop_for_dual_open_primary(self):
        """绕过 service 直接建开放 PRIMARY → DB 条件唯一约束拒绝（并发兜底）。"""
        self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
            source_business_type=FIXTURE_SOURCE,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrStaffAssignment.objects.create(
                    tenant_id=TENANT,
                    employment_relationship_id=self.emp,
                    organization_id=self.ai,
                    assignment_type=AssignmentType.PRIMARY,
                    effective_from=date(2025, 1, 1),
                    effective_to=None,
                )

    def test_switch_primary_closes_old_atomically(self):
        old = self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
            source_business_type=FIXTURE_SOURCE,
        )
        new = self.service.switch_primary(
            employment_relationship_id=self.emp,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
            source_business_type=FIXTURE_SOURCE,
        )
        old.refresh_from_db()
        self.assertEqual(old.effective_to, date(2026, 2, 1))
        self.assertEqual(old.status, "ENDED")
        self.assertEqual(new.effective_from, date(2026, 2, 1))
        self.assertIsNone(new.effective_to)
        # 人员有主岗，不会出现“无主岗”状态
        open_primary = HrStaffAssignment.objects.filter(
            tenant_id=TENANT,
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_to__isnull=True,
        )
        self.assertEqual(open_primary.count(), 1)

    def test_same_day_switch_cancels_old_segment(self):
        """同一生效日切换：旧段按 CANCELLED 处理（空段不落 ENDED），新段同日生效。"""
        old = self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.computer,
            source_business_type=FIXTURE_SOURCE,
        )
        new = self.service.switch_primary(
            employment_relationship_id=self.emp,
            effective_from=date(2024, 9, 1),
            organization_id=self.ai,
            source_business_type=FIXTURE_SOURCE,
        )
        old.refresh_from_db()
        self.assertEqual(old.status, "CANCELLED")
        self.assertEqual(old.effective_to, date(2024, 9, 1))
        self.assertEqual(new.effective_from, date(2024, 9, 1))

    def test_historical_overlap_primary_rejected(self):
        """新段 [2024-01-01, open) 与历史段 [2024-09-01, 2026-02-01) 重叠 → 拒绝。"""
        self.service.create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.computer,
            source_business_type=FIXTURE_SOURCE,
        )
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.switch_primary(
                employment_relationship_id=self.emp,
                effective_from=date(2024, 1, 1),
                organization_id=self.ai,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_OVERLAP")
