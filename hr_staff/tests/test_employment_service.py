"""S3 · EmploymentService 测试：关系开始/结束、结束自动关闭任职段、返聘不重复 Person。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType, RelationshipType
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment
from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.staff_master_service import StaffMasterService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "AUTHORIZED_CORRECTION"


class EmploymentServiceTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "王老师")
        self.staff = make_staff(TENANT, self.person, "T000777")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.emp_service = EmploymentService(TENANT)
        self.assign_service = AssignmentService(TENANT)

    def test_start_and_end_relationship(self):
        rel = self.emp_service.start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        assignment = self.assign_service.create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2020, 9, 1),
            organization_id=self.org,
            source_business_type=FIXTURE_SOURCE,
        )
        ended = self.emp_service.end_relationship(
            relationship_id=rel.id,
            effective_to=date(2026, 8, 1),
            reason_code="RETIREMENT",
        )
        ended.refresh_from_db()
        self.assertEqual(ended.status, "ENDED")
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "ENDED")
        self.assertEqual(assignment.effective_to, date(2026, 8, 1))

    def test_same_type_overlap_rejected(self):
        self.emp_service.start_relationship(
            staff_id=self.staff,
            relationship_type="CONTRACT",
            effective_from=date(2024, 1, 1),
        )
        with self.assertRaises(AssignmentPolicyViolation) as ctx:
            self.emp_service.start_relationship(
                staff_id=self.staff,
                relationship_type="CONTRACT",
                effective_from=date(2025, 1, 1),
            )
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_OVERLAP")

    def test_rehire_same_person_same_staff(self):
        """离职→返聘：同 Person 同 StaffMaster，第二关系生效（不重复创建人）。"""
        rel1 = self.emp_service.start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        self.emp_service.end_relationship(
            relationship_id=rel1.id,
            effective_to=date(2024, 6, 30),
            reason_code="RESIGNATION",
        )
        rel2 = self.emp_service.start_relationship(
            staff_id=self.staff,
            relationship_type="REHIRE",
            effective_from=date(2024, 9, 1),
        )
        self.assertEqual(rel2.staff_id_id, self.staff.id)
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(
                tenant_id=TENANT, staff_id=self.staff
            ).count(),
            2,
        )
