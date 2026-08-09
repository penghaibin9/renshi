"""S3 服务契约测试：ChangeService / ApprovalService / ImpactService / ValidationService。"""

from datetime import date

from django.test import TestCase

from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.services.approval_service import ApprovalService
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.impact_service import ImpactService
from hr_changes.services.validation_service import ValidationService
from hr_changes.tests.factories import (
    make_action,
    make_case,
    make_org,
    make_position,
    make_reason,
)
from hr_staff.services.employment_service import EmploymentService

TENANT = 1


class ChangeServiceCreateTests(TestCase):
    def setUp(self):
        self.action = make_action(TENANT)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        from hr_changes.tests.factories import make_person, make_staff

        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T7001")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )

    def _create(self, **kw):
        defaults = dict(
            staff_master_id=self.staff,
            action_id=self.action,
            reason_id=self.reason,
            requested_effective_at=date(2026, 9, 1),
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "old_value_display": "计算机学院",
                    "proposed_value_display": "人工智能学院",
                }
            ],
            target_org_id=self.org,
        )
        defaults.update(kw)
        return ChangeService(TENANT, actor_user_id=1).create_case(**defaults)

    def test_create_case_success(self):
        case = self._create()
        self.assertEqual(case.status, CaseStatus.DRAFT)
        self.assertTrue(case.case_no.startswith("HRCHG-"))
        self.assertEqual(case.proposals.count(), 1)

    def test_reason_mismatch_rejected(self):
        other_action = make_action(TENANT, ChangeActionCode.MANAGER_CHANGE)
        # action 为 MANAGER_CHANGE，reason 属于 ORG_TRANSFER → 不匹配
        with self.assertRaises(ChangeServiceError) as cm:
            self._create(action_id=other_action, reason_id=self.reason)
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_REASON")

    def test_disabled_action_rejected(self):
        self.action.enabled = False
        self.action.save()
        with self.assertRaises(ChangeServiceError) as cm:
            self._create()
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_ACTION")

    def test_effective_date_in_past_rejected(self):
        with self.assertRaises(ChangeServiceError) as cm:
            self._create(requested_effective_at=date(2020, 1, 1))
        self.assertEqual(cm.exception.code, "CHANGE_EFFECTIVE_DATE_INVALID")

    def test_invalid_proposal_field_rejected(self):
        with self.assertRaises(ChangeServiceError) as cm:
            self._create(
                proposals=[
                    {
                        "domain": "assignment",
                        "field_code": "salary",
                        "old_value_display": "a",
                        "proposed_value_display": "b",
                    }
                ]
            )
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_PAYLOAD")


class ChangeServiceWorkflowTests(TestCase):
    """提交→审批→批准→待生效；RETURNED→RESUBMIT；REJECTED 终局。"""

    def setUp(self):
        self.action = make_action(TENANT)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        self.target_org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        self.target_pos = make_position(TENANT, self.target_org, "AI-P001", max_incumbents=1)
        self.source_org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        # 空岗目标：make_case 不挂职位容量阻断
        self.case = make_case(
            TENANT,
            target_org=self.target_org,
            target_position=self.target_pos,
            source_org=self.source_org,
            status=CaseStatus.READY_TO_SUBMIT,
        )
        self.svc = ChangeService(TENANT, actor_user_id=1)

    def test_full_approval_flow(self):
        case = self.svc.submit(self.case.id)
        self.assertEqual(case.status, CaseStatus.SUBMITTED)
        case = self.svc.start_approval(case.id)
        self.assertEqual(case.status, CaseStatus.UNDER_APPROVAL)
        # 跨组织调动：SOURCE_ORG → TARGET_ORG → SCHOOL_HR 三步
        snap = ApprovalService(TENANT).get_current_snapshot(case)
        self.assertEqual(len(snap.steps_json), 3)
        # 逐步批准
        case = self.svc.approve(case.id)  # step1
        self.assertEqual(case.status, CaseStatus.UNDER_APPROVAL)
        case = self.svc.approve(case.id)  # step2
        self.assertEqual(case.status, CaseStatus.UNDER_APPROVAL)
        case = self.svc.approve(case.id)  # step3 → final
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)
        self.assertEqual(case.approved_effective_at, date(2026, 9, 1))

    def test_return_then_resubmit(self):
        case = self.svc.submit(self.case.id)
        case = self.svc.start_approval(case.id)
        case = self.svc.return_case(case.id, comment="补充材料")
        self.assertEqual(case.status, CaseStatus.RETURNED)
        case = self.svc.resubmit(case.id)
        self.assertEqual(case.status, CaseStatus.RESUBMITTED)
        case = self.svc.start_approval(case.id)
        self.assertEqual(case.status, CaseStatus.UNDER_APPROVAL)

    def test_reject_is_terminal(self):
        case = self.svc.submit(self.case.id)
        case = self.svc.start_approval(case.id)
        case = self.svc.reject(case.id, comment="不符合条件")
        self.assertEqual(case.status, CaseStatus.REJECTED)
        # REJECTED 不能再次提交/批准
        with self.assertRaises(ChangeServiceError):
            self.svc.approve(case.id)
        with self.assertRaises(ChangeServiceError):
            self.svc.resubmit(case.id)

    def test_withdraw_before_approval(self):
        case = self.svc.submit(self.case.id)
        case = self.svc.withdraw(case.id)
        self.assertEqual(case.status, CaseStatus.WITHDRAWN)

    def test_version_conflict(self):
        case = self.svc.submit(self.case.id)
        with self.assertRaises(ChangeServiceError) as cm:
            self.svc.submit(self.case.id, version=case.version + 5)
        self.assertEqual(cm.exception.code, "VERSION_CONFLICT")


class ImpactServiceTests(TestCase):
    def test_position_capacity_blocker(self):
        target_org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        target_pos = make_position(TENANT, target_org, "AI-P001", max_incumbents=1)
        # 已有人占用该岗位
        from hr_changes.tests.factories import make_person, make_staff

        staff2 = make_staff(TENANT, make_person(TENANT, "李某某"), "T7002")
        org2 = make_org(TENANT, "WX", "信息中心", date(2020, 1, 1))
        rel2 = EmploymentService(TENANT).start_relationship(
            staff_id=staff2, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        from hr_staff.services.assignment_service import AssignmentService

        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel2,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=target_org,
            position_id=target_pos,
        )
        case = make_case(TENANT, target_org=target_org, target_position=target_pos)
        blockers = ImpactService(TENANT).check_blockers(case)
        codes = {b["code"] for b in blockers}
        self.assertIn("CHANGE_POSITION_CAPACITY_CONFLICT", codes)

    def test_staff_departed_blocker(self):
        from hr_changes.tests.factories import make_person, make_staff

        staff = make_staff(TENANT, make_person(TENANT, "李某某"), "T7003")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        # 关闭关系模拟已离职
        rel.effective_to = date(2025, 1, 1)
        rel.status = "ENDED"
        rel.save()
        case = make_case(TENANT)
        case.staff_master_id = staff
        case.save()
        result = ImpactService(TENANT).compute(case)
        codes = {b["code"] for b in result["blockers"]}
        self.assertIn("CHANGE_SOURCE_ASSIGNMENT_MISMATCH", codes)

    def test_downstream_warnings(self):
        case = make_case(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        result = ImpactService(TENANT).compute(case)
        warn_codes = {w["code"] for w in result["warnings"]}
        self.assertIn("CONTRACT_REVIEW_REQUIRED", warn_codes)
        self.assertIn("ATTENDANCE_RULE_DIFF", warn_codes)
        self.assertIn("COMPENSATION_RECALC_REQUIRED", warn_codes)

    def test_impact_snapshot_versioned(self):
        case = make_case(TENANT)
        ImpactService(TENANT).compute(case)
        ImpactService(TENANT).compute(case)
        versions = list(case.impact_snapshots.order_by("snapshot_version").values_list("snapshot_version", flat=True))
        self.assertEqual(versions, [1, 2])


class ApprovalServiceTests(TestCase):
    def test_default_workflow_school_hr(self):
        case = make_case(TENANT, ChangeActionCode.MANAGER_CHANGE)
        snap = ApprovalService(TENANT).build_workflow(case)
        self.assertEqual(snap.steps_json[0]["approver_scope"], "SCHOOL_HR")
        self.assertEqual(len(snap.steps_json), 1)

    def test_cross_org_workflow_source_target_hr(self):
        source = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        target = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        case = make_case(TENANT, source_org=source, target_org=target)
        snap = ApprovalService(TENANT).build_workflow(case)
        scopes = [s["approver_scope"] for s in snap.steps_json]
        self.assertEqual(scopes, ["SOURCE_ORG", "TARGET_ORG", "SCHOOL_HR"])
        # 快照冻结后重算仍返回同一版本 id（已提交案件不再变）
        self.assertEqual(case.approval_instance_id, str(snap.id))


class ValidationServiceTests(TestCase):
    def test_missing_required_field(self):
        case = make_case(TENANT, ChangeActionCode.ORG_TRANSFER)
        result = ValidationService(TENANT).validate(case)
        blockers = {b["code"] for b in result["blockers"]}
        self.assertIn("CHANGE_INVALID_PAYLOAD", blockers)

    def test_data_correction_info(self):
        case = make_case(TENANT, ChangeActionCode.DATA_CORRECTION)
        result = ValidationService(TENANT).validate(case)
        infos = {i["code"] for i in result["infos"]}
        self.assertIn("CORRECTION_REQUIRES_APPROVAL", infos)
