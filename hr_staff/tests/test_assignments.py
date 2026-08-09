"""S6 · AssignmentHistorySelector 任职履历测试：as-of 历史、timeline、历史日期不显示当前学院。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.selectors.assignments import AssignmentHistorySelector, StaffNotFound
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1


def ctx(as_of=None):
    return HrStaffRequestContext(
        tenant_id=TENANT,
        as_of=as_of or date(2026, 8, 1),
        scope=HrStaffScope(scope_type="SCHOOL"),
    )


class AssignmentHistoryTests(TestCase):
    def setUp(self):
        self.computer = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.ai = make_org(TENANT, "AIXY", "人工智能学院", date(2026, 2, 1))
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.emp = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.computer,
        )
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=self.emp,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )

    def test_active_assignment_as_of_today_is_ai(self):
        data = AssignmentHistorySelector(ctx()).assignments(self.staff.id)
        self.assertEqual(len(data["active"]), 1)
        self.assertEqual(data["active"][0]["orgName"], "人工智能学院")

    def test_historical_as_of_shows_computer(self):
        data = AssignmentHistorySelector(ctx()).assignments(
            self.staff.id, as_of=date(2024, 10, 1)
        )
        self.assertEqual(len(data["active"]), 1)
        self.assertEqual(data["active"][0]["orgName"], "计算机学院")

    def test_historical_list_includes_ended_computer_segment(self):
        """as_of=今天：历史段（计算机）出现在 historical，不混入 active。"""
        data = AssignmentHistorySelector(ctx()).assignments(self.staff.id)
        historical_orgs = [h["orgName"] for h in data["historical"]]
        self.assertIn("计算机学院", historical_orgs)
        active_orgs = [a["orgName"] for a in data["active"]]
        self.assertNotIn("计算机学院", active_orgs)

    def test_timeline_never_shows_current_org_on_historical_date(self):
        """#55 负向：历史日期页面绝不显示当前学院。"""
        events = AssignmentHistorySelector(ctx()).timeline(self.staff.id)
        for e in events:
            if e["kind"] == "assignment" and e["effective_from"] <= date(2026, 1, 31):
                self.assertNotIn("AIXY", e["label"])

    def test_relationships_list(self):
        rels = AssignmentHistorySelector(ctx()).relationships(self.staff.id)
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["relationshipType"], "REGULAR_EMPLOYMENT")

    def test_staff_not_found(self):
        import uuid

        with self.assertRaises(StaffNotFound):
            AssignmentHistorySelector(ctx()).timeline(uuid.uuid4())
