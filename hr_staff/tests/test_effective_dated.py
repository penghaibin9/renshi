"""S3 · EffectiveDatedQueryService as-of 查询测试（含 #55 人物旅程 B：调岗历史）。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType, StaffStatus
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1


class EffectiveDatedTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.computer = make_org(
            TENANT, "JSXY", "计算机学院", date(2024, 1, 1), date(2026, 2, 1)
        )
        self.ai = make_org(
            TENANT, "AIXY", "人工智能学院", date(2026, 2, 1), None
        )
        self.emp = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        self.assign = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            effective_to=date(2026, 2, 1),
            organization_id=self.computer,
        )

    def test_as_of_historical_computer(self):
        qs = EffectiveDatedQueryService(TENANT)
        primary = qs.primary_assignment_as_of(self.staff.id, date(2024, 10, 1))
        self.assertEqual(primary.id, self.assign.id)
        self.assertEqual(primary.organization_id.id, self.computer.id)

    def test_switch_to_ai(self):
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=self.emp,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )
        qs = EffectiveDatedQueryService(TENANT)
        today_primary = qs.primary_assignment_as_of(self.staff.id, date(2026, 8, 1))
        self.assertEqual(today_primary.organization_id.id, self.ai.id)
        # 历史仍是计算机学院
        hist_primary = qs.primary_assignment_as_of(self.staff.id, date(2024, 10, 1))
        self.assertEqual(hist_primary.organization_id.id, self.computer.id)
        # 当前投影已更新
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.primary_assignment_id, today_primary.id)

    def test_status_derivation(self):
        qs = EffectiveDatedQueryService(TENANT)
        self.assertEqual(qs.status_as_of(self.staff.id, date(2026, 8, 1)), StaffStatus.ACTIVE)

    def test_org_name_as_of(self):
        qs = EffectiveDatedQueryService(TENANT)
        self.assertEqual(qs.org_name_as_of(self.computer.id, date(2024, 10, 1)), "计算机学院")

    def test_timeline_order(self):
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=self.emp,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )
        qs = EffectiveDatedQueryService(TENANT)
        events = qs.timeline(self.staff.id)
        self.assertGreaterEqual(len(events), 3)
        # 不允许历史日期读到当前学院
        for e in events:
            if e["kind"] == "assignment" and e["effective_from"] <= date(2026, 1, 31):
                self.assertNotIn("AIXY", e["label"])

    def test_boundary_semantics_half_open(self):
        """[2024-09-01, 2026-02-01)：结束日当天不属于本段。"""
        qs = EffectiveDatedQueryService(TENANT)
        self.assertIsNone(qs.primary_assignment_as_of(self.staff.id, date(2026, 2, 1)))

    def test_open_segment_closed_by_switch_still_restorable_as_of(self):
        """
        P0-1 回归：开放主岗（effective_to=None）被 switch_primary 关闭为 ENDED 后，
        历史 as-of 必须仍能还原该段（修复前 status=ACTIVE 过滤导致历史消失）。
        """
        # 独立场景，避免与 setUp 的已有段重叠
        person = make_person(TENANT, "独立教师")
        staff = make_staff(TENANT, person, "T009999")
        emp = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2021, 9, 1),
        )
        open_assign = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2025, 1, 1),
            organization_id=self.computer,
        )
        qs = EffectiveDatedQueryService(TENANT)
        # 2026-02 调到 AI：关闭开放段 → ENDED
        AssignmentService(TENANT).switch_primary(
            employment_relationship_id=emp,
            effective_from=date(2026, 2, 1),
            organization_id=self.ai,
        )
        open_assign.refresh_from_db()
        self.assertEqual(open_assign.status, "ENDED")
        self.assertEqual(open_assign.effective_to, date(2026, 2, 1))
        # 历史 as-of 在关闭段区间内必须还原
        hist = qs.primary_assignment_as_of(staff.id, date(2025, 6, 1))
        self.assertIsNotNone(hist)
        self.assertEqual(hist.id, open_assign.id)
        self.assertEqual(hist.organization_id.id, self.computer.id)
        # 当前 as-of 返回 AI
        today_primary = qs.primary_assignment_as_of(staff.id, date(2026, 8, 1))
        self.assertEqual(today_primary.organization_id.id, self.ai.id)
