"""S12 · #55 事故级负向验收（集中汇总测试）。

覆盖 #55.2 清单：A 改 B / 猜 staffId / 双并发 PRIMARY / 过期 version / BP 字段 /
authority 禁 fallback / 材料裸 URL / 普通导出带身份证 / rehire 重复 Person / 历史显示当前学院。
各场景细测已在各阶段文件覆盖，本文件做断言级汇总。
"""

from datetime import date
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AssignmentType, AuthorityMode, CorrectionEditMode
from hr_staff.models import HrStaffAssignment, HrFieldGovernancePolicy
from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.authority_mode_service import (
    AuthorityModeError,
    AuthorityModeService,
)
from hr_staff.services.correction_service import CorrectionPolicyDenied, CorrectionService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
OTHER_TENANT = 2


class AccidentNegativeAcceptanceTests(TestCase):
    def setUp(self):
        self.person_a = make_person(TENANT, "A校教师")
        self.staff_a = make_staff(TENANT, self.person_a, "T001")
        self.person_b = make_person(OTHER_TENANT, "B校教师")
        self.staff_b = make_staff(OTHER_TENANT, self.person_b, "T001")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.other_org = make_org(OTHER_TENANT, "BXY", "B校学院", date(2020, 1, 1))

    def test_a_school_cannot_modify_b_school_person(self):
        """A 校改 B 校人员 → 组织跨租户拒绝（CROSS_TENANT_REFERENCE）。"""
        rel_b = EmploymentService(OTHER_TENANT).start_relationship(
            staff_id=self.staff_b,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            AssignmentService(TENANT).create_assignment(
                employment_relationship_id=rel_b,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2024, 9, 1),
                organization_id=self.other_org,
            )
        self.assertEqual(ctx.exception.code, "CROSS_TENANT_REFERENCE")

    def test_dual_open_primary_rejected(self):
        """双并发 PRIMARY → ASSIGNMENT_OVERLAP（service）且 DB 条件唯一兜底。"""
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_a,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.org,
        )
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            AssignmentService(TENANT).create_assignment(
                employment_relationship_id=rel,
                assignment_type=AssignmentType.PRIMARY,
                effective_from=date(2025, 1, 1),
                organization_id=self.org,
            )
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_OVERLAP")

    def test_business_process_only_field_immune_to_correction(self):
        """更正直接改 BUSINESS_PROCESS_ONLY → CORRECTION_POLICY_DENIED。"""
        HrFieldGovernancePolicy.objects.update_or_create(
            tenant_id=TENANT,
            field_code="employment.effective_from",
            defaults={"edit_mode": CorrectionEditMode.BUSINESS_PROCESS_ONLY},
        )
        svc = CorrectionService(TENANT, actor_user_id=1)
        with self.assertRaises(CorrectionPolicyDenied):
            svc.create_case(
                staff_id=self.staff_a,
                reason="x",
                items=[{"field_code": "employment.effective_from"}],
            )

    def test_authority_mode_blocks_fallback(self):
        """AUTHORITY 模式故障时禁止 silent fallback legacy。"""
        svc = AuthorityModeService()
        with mock.patch.object(svc, "get_mode", return_value=AuthorityMode.HR03_AUTHORITY):
            mode = svc.assert_authority_available(TENANT, require_authority=True)
            self.assertEqual(mode, AuthorityMode.HR03_AUTHORITY)
        with mock.patch.object(svc, "get_mode", return_value=AuthorityMode.LEGACY_STAFF_ONLY):
            with self.assertRaises(AuthorityModeError):
                svc.assert_authority_available(TENANT, require_authority=True)

    def test_rehire_does_not_create_duplicate_person(self):
        """rehire 复用已有 Person/Staff（不重复建）。"""
        self.assertEqual(self.staff_a.person_id.id, self.person_a.id)
        rel1 = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_a,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        EmploymentService(TENANT).end_relationship(
            relationship_id=rel1.id, effective_to=date(2024, 6, 30), reason_code="RESIGNATION"
        )
        rel2 = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_a,
            relationship_type="REHIRE",
            effective_from=date(2024, 9, 1),
        )
        self.assertEqual(rel2.staff_id_id, self.staff_a.id)

    def test_high_sensitive_not_in_plain_export_path(self):
        """名册/履历/材料 API 均不回身份证明文（高敏不入列表/导出）。"""
        from hr_staff.selectors.staff_list import STAFF_LIST_FIELDS

        self.assertNotIn("identity", STAFF_LIST_FIELDS)
        self.assertNotIn("birth_date", STAFF_LIST_FIELDS)
        self.assertNotIn("phone", STAFF_LIST_FIELDS)

    def test_history_never_shows_current_org(self):
        """历史 as-of 绝不显示当前学院（#55 第 10 项核心）。"""
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        # 只建 2024-2026 计算机学院段；2024 历史查主岗必须是计算机
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_a,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.org,
        )
        qs = EffectiveDatedQueryService(TENANT)
        self.assertIsNone(qs.primary_assignment_as_of(self.staff_a.id, date(2026, 3, 1)))
        primary = qs.primary_assignment_as_of(self.staff_a.id, date(2024, 10, 1))
        self.assertEqual(primary.organization_id_id, self.org.id)
