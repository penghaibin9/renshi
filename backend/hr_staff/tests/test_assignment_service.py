"""S3 · AssignmentService 不变量测试：并发 PRIMARY、重叠、跨租户、主岗切换原子。"""

from datetime import date
from decimal import Decimal

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

    def _make_position(self, *, org, code="P001", lifecycle="ACTIVE"):
        from hr_structure.models import HrPostCatalog, HrPostCatalogVersion, HrPosition

        catalog = HrPostCatalog.objects.create(
            tenant_id=TENANT,
            stable_code=f"CAT-{code}",
        )
        catalog_version = HrPostCatalogVersion.objects.create(
            catalog_id=catalog,
            tenant_id=TENANT,
            name=f"岗位目录-{code}",
            category="PROFESSIONAL_TECHNICAL",
            subcategory="TEACHER",
            validity_from=date(2024, 1, 1),
            status="ACTIVE",
            version_no=1,
        )
        return HrPosition.objects.create(
            tenant_id=TENANT,
            position_code=code,
            organization_id=org,
            post_catalog_version_id=catalog_version,
            validity_from=date(2024, 1, 1),
            lifecycle_status=lifecycle,
            max_incumbents=2,
            allow_multiple_incumbents=True,
        )

    def test_assignment_cannot_outlive_employment_relationship(self):
        self.emp.effective_to = date(2025, 1, 1)
        self.emp.save(update_fields=["effective_to", "updated_at"])
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.CONCURRENT,
                effective_from=date(2024, 9, 1),
                effective_to=date(2025, 2, 1),
                organization_id=self.computer,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_OUTSIDE_RELATIONSHIP")

    def test_position_must_belong_to_selected_org_as_of_effective_date(self):
        position = self._make_position(org=self.computer, code="P-ORG")
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.CONCURRENT,
                effective_from=date(2024, 9, 1),
                organization_id=self.ai,
                position_id=position,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "POSITION_ORG_MISMATCH")

    def test_frozen_position_cannot_receive_new_assignment(self):
        position = self._make_position(org=self.computer, code="P-FROZEN", lifecycle="FROZEN")
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.service.create_assignment(
                employment_relationship_id=self.emp,
                assignment_type=AssignmentType.CONCURRENT,
                effective_from=date(2024, 9, 1),
                organization_id=self.computer,
                position_id=position,
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "POSITION_NOT_ASSIGNABLE")

    def test_overlapping_total_fte_cannot_exceed_school_policy(self):
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
                assignment_type=AssignmentType.CONCURRENT,
                effective_from=date(2025, 1, 1),
                organization_id=self.ai,
                fte=Decimal("0.75"),
                source_business_type=FIXTURE_SOURCE,
            )
        self.assertEqual(ctx.exception.code, "FTE_POLICY_EXCEEDED")
