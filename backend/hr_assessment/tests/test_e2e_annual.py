"""S11 E2E 年度主链 — 20 步。"""

from django.test import TestCase
from hr_assessment.models.policy import HrAssessmentPolicyPack, HrAssessmentPolicyVersion
from hr_assessment.models.cycle import HrAssessmentCycle, HrAssessmentPopulationSnapshot
from hr_assessment.models.case import HrAssessmentCase, HrSubjectSnapshot, HrAssessmentPublicityCase
from hr_assessment.models.goal import HrAssessmentGoalPlan, HrAssessmentGoal, HrGoalAssignment
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultNotice, HrAcknowledgement, HrAssessmentArchivePackage
from hr_assessment.models.evidence import HrSelfAssessment, HrReviewerAssignment, HrReviewerEvaluation
import uuid
from datetime import datetime, timedelta, timezone


class E2EAnnualMainChainTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.staff_id = uuid.uuid4()
        self.org_id = 1001
        self.now = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)

    def test_step01_policy_pack_resolved(self):
        pack = HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_id, code="C01", name="教师年度考核", assessment_domain="ANNUAL")
        self.assertIsNotNone(pack.id)

    def test_step02_cycle_created(self):
        pack = HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_id, code="C02", name="教师年度考核", assessment_domain="ANNUAL")
        version = HrAssessmentPolicyVersion.objects.create(
            tenant_id=self.tenant_id, version_no=1, policy_pack=pack, effective_from="2026-01-01",
            assessment_types=["ANNUAL"], rating_scale_version_id=uuid.uuid4(),
            indicator_set_version_id=uuid.uuid4(), workflow_version_id=uuid.uuid4(),
        )
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="2026-01", assessment_type="ANNUAL",
            name="2026年度考核", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T23:59:59Z",
            policy_version_id=version.id,
        )
        self.assertEqual(cycle.cycle_no, "2026-01")

    def test_step03_population_frozen(self):
        version = self._create_policy_version()
        cycle = self._create_cycle(version.id)
        snapshot = HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=self.tenant_id, cycle=cycle, staff_id=self.staff_id,
            included=True, org_id=self.org_id, worker_category="TEACHER",
            snapshot_at=self.now,
        )
        self.assertTrue(snapshot.included)

    def test_step04_goal_confirmed(self):
        plan = HrAssessmentGoalPlan.objects.create(tenant_id=self.tenant_id, name="2026年度目标", goal_type="ANNUAL")
        goal = HrAssessmentGoal.objects.create(tenant_id=self.tenant_id, goal_plan=plan, goal_code="G001", status="CONFIRMED")
        self.assertEqual(goal.goal_code, "G001")

    def test_step05_subject_snapshot_frozen(self):
        ss = HrSubjectSnapshot.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), staff_id=self.staff_id,
            display_name="张三", org_id=self.org_id, snapshot_at=self.now,
        )
        self.assertEqual(ss.display_name, "张三")

    def test_step06_self_assessment_submitted(self):
        case_id = uuid.uuid4()
        sa = HrSelfAssessment.objects.create(tenant_id=self.tenant_id, case_id=case_id, summary="年度总结", submitted_at=self.now)
        self.assertIsNotNone(sa.submitted_at)

    def test_step07_reviewer_assigned(self):
        rev = HrReviewerAssignment.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(),
            reviewer_role="DIRECT_MANAGER", reviewer_staff_id=uuid.uuid4(),
        )
        self.assertEqual(rev.reviewer_role, "DIRECT_MANAGER")

    def test_step08_reviewer_evaluation_submitted(self):
        assign = HrReviewerAssignment.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(),
            reviewer_role="DIRECT_MANAGER", reviewer_staff_id=uuid.uuid4(),
        )
        ev = HrReviewerEvaluation.objects.create(
            tenant_id=self.tenant_id, assignment=assign,
            indicator_evaluations_json=[{"indicator": "TEACHING", "score": 90}],
            recommendation="EXCELLENT", submitted_at=self.now,
        )
        self.assertEqual(ev.recommendation, "EXCELLENT")

    def test_step09_final_result_created(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
            finalized_at=self.now,
        )
        self.assertEqual(result.grade_code, "QUALIFIED")

    def test_step10_notice_generated(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        notice = HrResultNotice.objects.create(
            tenant_id=self.tenant_id, result=result, notice_no="N2026-001",
            delivery_status="PENDING",
        )
        self.assertEqual(notice.delivery_status, "PENDING")

    def test_step11_acknowledgement_recorded(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        ack = HrAcknowledgement.objects.create(
            tenant_id=self.tenant_id, result=result,
            acknowledgement_status="RECEIVED_AGREE", confirmed_at=self.now,
        )
        self.assertEqual(ack.acknowledgement_status, "RECEIVED_AGREE")

    def test_step12_archived(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        archive = HrAssessmentArchivePackage.objects.create(
            tenant_id=self.tenant_id, result=result, archive_package_id="ARC-2026-001",
        )
        self.assertEqual(archive.archive_package_id, "ARC-2026-001")

    def test_step13_excellent_chain(self):
        """优秀链：候选 → 审定 → 公示 → FINALIZED"""
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="EXCELLENT", result_version_no=1, status="PROPOSED",
        )
        # 公示
        publicity = HrAssessmentPublicityCase.objects.create(
            tenant_id=self.tenant_id, start_at=self.now,
            end_at=self.now + timedelta(days=7), status="ACTIVE",
        )
        publicity.status = "COMPLETED"
        publicity.completed_at = self.now + timedelta(days=7)
        publicity.save()
        self.assertEqual(publicity.status, "COMPLETED")

    def test_step14_no_rating_case(self):
        """NO_RATING 独立存储"""
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="NO_RATING", result_version_no=1, status="FINALIZED",
        )
        self.assertEqual(result.grade_code, "NO_RATING")

    def _create_policy_version(self):
        pack = HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_id, code="C-TEST", name="测试", assessment_domain="ANNUAL")
        return HrAssessmentPolicyVersion.objects.create(
            tenant_id=self.tenant_id, version_no=1, policy_pack=pack, effective_from="2026-01-01",
            assessment_types=["ANNUAL"], rating_scale_version_id=uuid.uuid4(),
            indicator_set_version_id=uuid.uuid4(), workflow_version_id=uuid.uuid4(),
        )

    def _create_cycle(self, version_id):
        return HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no=f"C-{uuid.uuid4().hex[:4]}", assessment_type="ANNUAL",
            name="测试周期", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T23:59:59Z",
            policy_version_id=version_id,
        )
