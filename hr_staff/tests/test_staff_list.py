"""S4 · StaffListSelector 名册查询测试：过滤、scope、行组装、高敏不入列表。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffScope, HrStaffRequestContext
from hr_staff.models import HrStaffAssignment
from hr_staff.selectors.staff_list import STAFF_LIST_FIELDS, StaffListSelector
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
OTHER_TENANT = 2


def ctx(scope_type="SCHOOL", org_id=None, as_of=None):
    return HrStaffRequestContext(
        tenant_id=TENANT,
        as_of=as_of or date(2026, 8, 1),
        scope=HrStaffScope(scope_type=scope_type, org_id=org_id),
    )


class StaffListSelectorTests(TestCase):
    def setUp(self):
        self.computer = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.ai = make_org(TENANT, "AIXY", "人工智能学院", date(2026, 2, 1))
        # 老师 A：2020 入职，当前在 AI 学院
        self.person_a = make_person(TENANT, "张某某")
        self.staff_a = make_staff(TENANT, self.person_a, "T001238")
        rel_a = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_a,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel_a,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.computer,
        )
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=rel_a,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )
        # 老师 B：仍在计算机学院
        self.person_b = make_person(TENANT, "李四")
        self.staff_b = make_staff(TENANT, self.person_b, "T000001")
        rel_b = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff_b,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel_b,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2020, 9, 1),
            organization_id=self.computer,
        )
        # 老师 C：B 校（跨租户，必须不可见）
        self.person_c = make_person(OTHER_TENANT, "王五")
        self.staff_c = make_staff(OTHER_TENANT, self.person_c, "T000001")

    def test_school_scope_lists_all_tenant_staff(self):
        result = StaffListSelector(ctx()).rows({}, page=1, page_size=50)
        self.assertEqual(result["total"], 2)
        ids = {item["staff_no"] for item in result["items"]}
        self.assertEqual(ids, {"T001238", "T000001"})

    def test_tenant_isolation_cross_tenant_invisible(self):
        """B 校 staffId 猜 A 校 → 名册不存在（跨租户 fail-closed）。"""
        result = StaffListSelector(ctx()).rows({}, page=1, page_size=50)
        self.assertNotIn("王五", {i["legal_name"] for i in result["items"]})

    def test_scope_college_filters_by_current_org(self):
        result = StaffListSelector(
            ctx(scope_type="COLLEGE", org_id=self.ai.id)
        ).rows({}, page=1, page_size=50)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["staff_no"], "T001238")

    def test_keyword_search(self):
        result = StaffListSelector(ctx()).rows({"keyword": "李四"}, page=1, page_size=50)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["staff_no"], "T000001")

    def test_status_filter(self):
        result = StaffListSelector(ctx()).rows(
            {"status": "ACTIVE"}, page=1, page_size=50
        )
        self.assertEqual(result["total"], 2)

    def test_row_current_org_is_ai_for_teacher_a(self):
        result = StaffListSelector(ctx()).rows({}, page=1, page_size=50)
        row_a = next(i for i in result["items"] if i["staff_no"] == "T001238")
        self.assertEqual(row_a["org_name"], "人工智能学院")
        self.assertEqual(row_a["date_joining"], "2020-09-01")
        self.assertIn("has_future_change", row_a)

    def test_default_row_fields_contain_no_high_sensitive(self):
        result = StaffListSelector(ctx()).rows({}, page=1, page_size=50)
        for item in result["items"]:
            self.assertEqual(
                set(item.keys()),
                STAFF_LIST_FIELDS,
                "名册行字段必须与 STAFF_LIST_FIELDS 完全一致（无身份证/生日/手机等）",
            )

    def test_pagination(self):
        result = StaffListSelector(ctx()).rows({}, page=1, page_size=1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["page"], 1)
