"""S6 借调挂职契约测试：link 创建/延期/超期/返岗/原岗无效 exception。"""

from datetime import date, timedelta

from django.test import TestCase

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrTemporaryAssignmentExtension, HrTemporaryAssignmentLink
from hr_changes.services.apply_service import ApplyService
from hr_changes.services.change_service import ChangeService
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
    source_position = make_position(TENANT, src_org, "SRC-P-T5101")
    rel = EmploymentService(TENANT).start_relationship(
        staff_id=staff, relationship_type="REGULAR_EMPLOYMENT",
        effective_from=date(2024, 9, 1),
    )
    source = AssignmentService(TENANT).create_assignment(
        employment_relationship_id=rel,
        assignment_type=AssignmentType.PRIMARY,
        effective_from=date(2024, 9, 1),
        organization_id=src_org,
        position_id=source_position,
        post_catalog_id=source_position.post_catalog_version_id,
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


class TemporaryCreateWriterTests(TestCase):
    def _authority_facts(self, staff_no):
        staff = make_staff(TENANT, make_person(TENANT, staff_no), staff_no)
        source_org = make_org(
            TENANT,
            f"SRC-{staff_no}",
            "原单位",
            date(2020, 1, 1),
        )
        target_org = make_org(
            TENANT,
            f"TMP-{staff_no}",
            "临时单位",
            date(2020, 1, 1),
        )
        source_position = make_position(
            TENANT,
            source_org,
            f"SRC-P-{staff_no}",
            max_incumbents=1,
        )
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        source = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=source_org,
            position_id=source_position,
            post_catalog_id=source_position.post_catalog_version_id,
            source_business_type="MIGRATION_VERIFIED",
        )
        return staff, target_org, source

    def test_secondment_writer_creates_and_applies_complete_authority_contract(self):
        staff, target_org, source = self._authority_facts("T5110")
        action = make_action(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        reason = make_reason(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        effective_at = date.today()
        return_at = effective_at + timedelta(days=180)

        case = TemporaryAssignmentService(
            TENANT,
            actor_user_id=1,
        ).create_temporary_case(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            target_org_id=target_org.id,
            requested_effective_at=effective_at,
            expected_return_at=return_at,
        )

        self.assertEqual(case.status, "DRAFT")
        self.assertEqual(case.source_assignment_id_id, source.id)
        self.assertEqual(case.source_org_id_id, source.organization_id_id)
        self.assertEqual(case.source_position_id_id, source.position_id_id)
        self.assertEqual(case.target_org_id_id, target_org.id)
        proposals = {
            proposal.field_code: proposal.proposed_value_ref
            for proposal in case.proposals.all()
        }
        self.assertEqual(proposals["organization"], str(target_org.id))
        self.assertEqual(proposals["expected_return_at"], return_at.isoformat())
        self.assertEqual(proposals["source_policy"], "KEEP_ACTIVE")
        workflow = ChangeService(TENANT, actor_user_id=1)
        case = workflow.submit(case.id)
        case = workflow.start_approval(case.id)
        case = workflow.approve_all(case.id)
        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)

        self.assertEqual(case.status, "EFFECTIVE")
        temporary = HrStaffAssignment.objects.get(
            tenant_id=TENANT,
            employment_relationship_id=source.employment_relationship_id,
            assignment_type=AssignmentType.SECONDMENT,
        )
        self.assertEqual(temporary.organization_id_id, target_org.id)
        self.assertEqual(temporary.effective_from, effective_at)
        self.assertEqual(temporary.effective_to, return_at)
        source.refresh_from_db()
        self.assertIsNone(source.effective_to)
        link = HrTemporaryAssignmentLink.objects.get(change_case_id=case)
        self.assertEqual(link.source_assignment_id_id, source.id)
        self.assertEqual(link.temporary_assignment_id_id, temporary.id)
        self.assertEqual(link.expected_return_at, return_at)
        self.assertEqual(link.source_assignment_status_policy, "KEEP_ACTIVE")

    def test_attachment_writer_rejects_unsupported_source_policy(self):
        staff, target_org, _source = self._authority_facts("T5111")
        action = make_action(TENANT, ChangeActionCode.TEMPORARY_ATTACHMENT)
        reason = make_reason(TENANT, ChangeActionCode.TEMPORARY_ATTACHMENT)
        draft = TemporaryAssignmentService(TENANT).create_temporary_case(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            target_org_id=target_org.id,
            requested_effective_at=date.today(),
            expected_return_at=date.today() + timedelta(days=90),
        )
        self.assertEqual(draft.status, "DRAFT")
        self.assertEqual(draft.action_id.code, ChangeActionCode.TEMPORARY_ATTACHMENT)
        with self.assertRaises(TemporaryServiceError) as caught:
            TemporaryAssignmentService(TENANT).create_temporary_case(
                staff_master_id=staff,
                action_id=action,
                reason_id=reason,
                target_org_id=target_org.id,
                requested_effective_at=date.today(),
                expected_return_at=date.today() + timedelta(days=90),
                source_policy="SUSPEND",
            )
        self.assertEqual(caught.exception.code, "CHANGE_INVALID_ACTION")

    def test_secondment_can_select_and_reserve_a_real_target_position(self):
        from hr_changes.integrations.hr02 import PositionGate

        staff, target_org, _source = self._authority_facts("T5112")
        target_position = make_position(
            TENANT, target_org, "TMP-P-T5112", max_incumbents=1
        )
        action = make_action(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        reason = make_reason(TENANT, ChangeActionCode.TEMPORARY_SECONDMENT)
        case = TemporaryAssignmentService(TENANT, actor_user_id=1).create_temporary_case(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            target_org_id=target_org.id,
            target_position_id=target_position.id,
            requested_effective_at=date.today(),
            expected_return_at=date.today() + timedelta(days=90),
        )
        self.assertEqual(case.target_position_id_id, target_position.id)
        workflow = ChangeService(TENANT, actor_user_id=1)
        case = workflow.submit(case.id)
        case = workflow.start_approval(case.id)
        case = workflow.approve_all(case.id)
        reservation = PositionGate(TENANT).reserve_for_case(case)
        self.assertIsNotNone(reservation)
        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)
        temporary = HrStaffAssignment.objects.get(
            tenant_id=TENANT,
            assignment_type=AssignmentType.SECONDMENT,
            source_business_id=case.case_no,
        )
        self.assertEqual(case.status, "EFFECTIVE")
        self.assertEqual(temporary.position_id_id, target_position.id)
        self.assertEqual(
            temporary.post_catalog_id_id, target_position.post_catalog_version_id_id
        )


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
        self.assertIsNotNone(position)
        AssignmentService(TENANT).close_assignment(
            assignment_id=self.source.id,
            effective_to=date(2026, 9, 1),
        )
        PositionService(Hr02Scope(scope_type="SCHOOL", tenant_id=TENANT)).close(
            position.id,
            reason="撤销",
        )
        with self.assertRaises(ReturnServiceError) as cm:
            ReturnService(TENANT).plan_return(self.link.id)
        self.assertEqual(cm.exception.code, "RETURN_TARGET_INVALID")
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, "RETURN_TARGET_INVALID")

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
