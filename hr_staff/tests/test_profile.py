"""S5 · ProfileSelector 主档 bootstrap 测试：as-of、scope、高敏不泄漏、历史视图标记。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffScope, HrStaffRequestContext
from hr_staff.selectors.profile import ProfileSelector, StaffNotFound, StaffScopeDenied
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.person_identity_service import PersonIdentityService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1


def ctx(scope_type="SCHOOL", org_id=None, as_of=None, staff_ids=None):
    # as_of=None → context 自动取学校时区今天（真实"当前"视图）
    return HrStaffRequestContext(
        tenant_id=TENANT,
        as_of=as_of,
        scope=HrStaffScope(
            scope_type=scope_type, org_id=org_id, staff_ids=frozenset(staff_ids or [])
        ),
    )


class ProfileBootstrapTests(TestCase):
    def setUp(self):
        self.computer = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.ai = make_org(TENANT, "AIXY", "人工智能学院", date(2026, 2, 1))
        self.person = PersonIdentityService().create_person_with_identity(
            tenant_id=TENANT,
            legal_name="张某某",
            birth_date=date(1988, 5, 1),
            document_number="110101198805010011",
        )
        self.staff = make_staff(TENANT, self.person, "T001238")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.computer,
        )
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=rel,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )

    def test_current_profile_shows_ai(self):
        data = ProfileSelector(ctx()).bootstrap(self.staff.id)
        self.assertEqual(data["currentFacts"]["primaryAssignment"]["orgName"], "人工智能学院")
        self.assertEqual(data["identityHeader"]["staffNo"], "T001238")
        self.assertFalse(data["isHistoricalView"])

    def test_as_of_history_shows_computer(self):
        data = ProfileSelector(ctx(as_of=date(2024, 10, 1))).bootstrap(self.staff.id)
        self.assertEqual(data["currentFacts"]["primaryAssignment"]["orgName"], "计算机学院")
        self.assertTrue(data["isHistoricalView"])

    def test_high_sensitive_not_in_bootstrap(self):
        """身份证明文绝不出现在 bootstrap；只给掩码。"""
        data = ProfileSelector(ctx()).bootstrap(self.staff.id)
        self.assertNotIn("110101198805010011", str(data))
        self.assertTrue(
            data["identitySummary"]["maskedIdentityNo"].endswith("****0011")
        )

    def test_staff_not_found_404(self):
        import uuid

        with self.assertRaises(StaffNotFound):
            ProfileSelector(ctx()).bootstrap(uuid.uuid4())

    def test_college_scope_denies_out_of_scope(self):
        other_staff = make_staff(TENANT, make_person(TENANT, "李四"), "T999999")
        with self.assertRaises(StaffScopeDenied):
            ProfileSelector(ctx(scope_type="COLLEGE", org_id=self.ai.id)).bootstrap(
                other_staff.id
            )

    def test_self_scope_denies_other(self):
        import uuid

        with self.assertRaises(StaffScopeDenied):
            ProfileSelector(
                ctx(scope_type="SELF", staff_ids=[uuid.uuid4()])
            ).bootstrap(self.staff.id)

    def test_employment_status_derived(self):
        data = ProfileSelector(ctx()).bootstrap(self.staff.id)
        self.assertEqual(data["identityHeader"]["employmentStatus"], "ACTIVE")
