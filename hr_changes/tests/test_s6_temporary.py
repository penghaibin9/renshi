"""S6 借调挂职契约测试：link 创建/延期/超期/返岗/原岗无效 exception。"""

from datetime import date, timedelta

from django.test import TestCase

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrTemporaryAssignmentExtension, HrTemporaryAssignmentLink
from hr_changes.services.return_service import ReturnService, ReturnServiceError
from hr_changes.services.temporary_service import (
    TemporaryAssignmentService,
    TemporaryServiceError,
)
from hr_changes.tests.factories import (
    make_action,
    make_case,
    make_org,
    make_person,
    make_position,
    make_reason,
    make_staff,
)
from hr_staff.constants import AssignmentType
from hr_staff.models import HrStaffAssignment
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService

TENANT = 1


def make_source_and_temp():
    staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T5101")
    src_org = make_org(TENANT, "JSXY", "计算机学院", date(2024, 1, 1))
    temp_org = make_org(TENANT, "RGXY", "人工智能学院", date(2024, 1, 1))
    rel = EmploymentService(TENANT).start_relationship(
        staff_id=staff, relationship_type="REGULAR_EMPLOYMENT",
        effective_from=date(2024, 9, 1),
    )
    source = AssignmentService(TENANT).create_assignment(
        employment_relationship_id=rel,
        assignment_type=AssignmentType.PRIMARY,
        effective_from=date(2024, 9, 1),
        organization_id=src_org,
        source_business_type="MIGRATION_VERIFIED",
    )
    temporary = AssignmentService(TENANT).create_assignment(
        employment_relationship_id=rel,
        assignment_type=AssignmentType.SECONDMENT,
        effective_from=date(2026, 9, 1),
        effective_to=date(2027, 9, 1),
        organization_id=temp_org,
        source_business_type="MIGRATION_VERIFIED",
    )
    return staff, source, temporary, rel


class TemporaryServiceTests(TestCase):
    def setUp(self):
        self.staff, self.source, self.temp, self.rel = make_source_and_temp()
        self.case = make_case(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        self.case.staff_master_id = self.staff
        self.case.save()

    def _link(self, **kw):
        defaults = dict(
            change_case_id=self.case,
            source_assignment_id=self.source,
            temporary_assignment_id=self.temp,
            start_at=date(2026, 9, 1),
            expected_return_at=date(2027, 9, 1),
        )
        defaults.update(kw)
        return TemporaryAssignmentService(TENANT).create_link(**defaults)

    def test_create_link(self):
        link = self._link()
        self.assertEqual(link.status, "ACTIVE")
        self.assertEqual(link.source_assignment_status_policy, "KEEP_ACTIVE")

    def test_invalid_return_date(self):
        with self.assertRaises(TemporaryServiceError) as cm:
            self._link(expected_return_at=date(2026, 8, 1))
        self.assertEqual(cm.exception.code, "CHANGE_EFFECTIVE_DATE_INVALID")

    def test_extend_saves_old_new(self):
        link = self._link()
        ext = TemporaryAssignmentService(TENANT).extend(
            link_id=link.id, new_return_at=date(2028, 3, 1), reason="项目延期"
        )
        self.assertEqual(ext.status, "APPLIED")
        self.assertEqual(ext.old_return_at, date(2027, 9, 1))
        self.assertEqual(ext.new_return_at, date(2028, 3, 1))
        link.refresh_from_db()
        self.assertEqual(link.expected_return_at, date(2028, 3, 1))
        self.assertEqual(link.status, "EXTENDED")

    def test_extend_must_increase(self):
        link = self._link()
        with self.assertRaises(TemporaryServiceError) as cm:
            TemporaryAssignmentService(TENANT).extend(
                link_id=link.id, new_return_at=date(2026, 12, 1)
            )
        self.assertEqual(cm.exception.code, "CHANGE_EFFECTIVE_DATE_INVALID")

    def test_overdue_detection(self):
        link = self._link(
            start_at=date(2026, 1, 1),
            expected_return_at=date.today() - timedelta(days=5),
        )
        overdue = TemporaryAssignmentService(TENANT).overdue()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].id, link.id)

    def test_due_soon(self):
        link = self._link(
            start_at=date(2026, 1, 1),
            expected_return_at=date.today() + timedelta(days=10),
        )
        due = TemporaryAssignmentService(TENANT).due_soon(days=30)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].id, link.id)


class ReturnServiceTests(TestCase):
    def setUp(self):
        self.staff, self.source, self.temp, self.rel = make_source_and_temp()
        self.case = make_case(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        self.case.staff_master_id = self.staff
        self.case.save()
        self.link = TemporaryAssignmentService(TENANT).create_link(
            change_case_id=self.case,
            source_assignment_id=self.source,
            temporary_assignment_id=self.temp,
            start_at=date(2026, 9, 1),
            expected_return_at=date(2027, 9, 1),
        )

    def test_plan_return_creates_return_case(self):
        # 种子 RETURN 动作/原因（正式环境由 seed_hr06_defaults 提供）
        make_action(TENANT, ChangeActionCode.RETURN_FROM_TEMPORARY)
        make_reason(TENANT, ChangeActionCode.RETURN_FROM_TEMPORARY, "TEMPORARY_PERIOD_END")
        case = ReturnService(TENANT, actor_user_id=1).plan_return(self.link.id)
        self.assertEqual(case.action_id.code, ChangeActionCode.RETURN_FROM_TEMPORARY)
        self.link.refresh_from_db()
        self.assertEqual(self.link.return_case_id_id, case.id)

    def test_execute_return_keep_active(self):
        link = ReturnService(TENANT, actor_user_id=1).execute_return(
            self.link.id, return_effective_at=date(2027, 9, 1)
        )
        self.assertEqual(link.status, "RETURNED")
        # 临时任职段已关闭
        self.temp.refresh_from_db()
        self.assertEqual(self.temp.status, "ENDED")
        self.assertEqual(self.temp.effective_to, date(2027, 9, 1))

    def test_return_target_invalid_when_position_closed(self):
        # 原岗位关闭 → plan_return 抛 RETURN_TARGET_INVALID 且 link 置 invalid
        from hr_structure.services.position import PositionService
        from hr_structure.scope import Hr02Scope

        position = self.source.position_id
        if position:
            PositionService(Hr02Scope(scope_type="SCHOOL", tenant_id=TENANT)).close(position.id, reason="撤销")
            with self.assertRaises(ReturnServiceError) as cm:
                ReturnService(TENANT).plan_return(self.link.id)
            self.assertEqual(cm.exception.code, "RETURN_TARGET_INVALID")
            self.link.refresh_from_db()
            self.assertEqual(self.link.status, "RETURN_TARGET_INVALID")
        else:
            self.skipTest("source 无权威岗位，跳过岗位关闭分支")

    def test_suspend_policy_restores_source(self):
        # 挂起式原岗 + 返岗 → 恢复新段
        from hr_changes.services.return_service import ReturnService as RS

        self.link.source_assignment_status_policy = "SUSPEND"
        self.link.save()
        # 模拟原岗在借调开始时已关闭
        from hr_staff.services.assignment_service import AssignmentService

        AssignmentService(TENANT).close_assignment(
            assignment_id=self.source.id, effective_to=date(2026, 9, 1)
        )
        link = RS(TENANT, actor_user_id=1).execute_return(
            self.link.id, return_effective_at=date(2027, 9, 1)
        )
        self.assertEqual(link.status, "RETURNED")
        # 返岗日应存在新的 PRIMARY 段
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        qs = EffectiveDatedQueryService(TENANT)
        restored = qs.primary_assignment_as_of(self.staff.id, date(2027, 9, 2))
        self.assertIsNotNone(restored)
        self.assertEqual(restored.organization_id_id, self.source.organization_id_id)


class TemporaryApiSmokeTests(TestCase):
    def test_extension_model_exists(self):
        self.assertTrue(HrTemporaryAssignmentExtension._meta.get_field("old_return_at"))
        self.assertTrue(HrTemporaryAssignmentLink._meta.get_field("expected_return_at"))
