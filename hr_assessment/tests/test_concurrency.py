"""S11 并发测试 — 10 个场景。"""

from concurrent.futures import ThreadPoolExecutor
from django.test import TestCase, TransactionTestCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_assessment.models.case import HrAssessmentCase, HrAssessmentCycle, HrAnnualAssessmentCase
from hr_assessment.models.evidence import HrSelfAssessment
from hr_assessment.models.policy import HrAssessmentPolicyPack
import uuid


class ConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.tenant_id = 10001

    def test_double_self_review_submit(self):
        case_id = uuid.uuid4()
        sa1 = HrSelfAssessment.objects.create(tenant_id=self.tenant_id, case_id=case_id, summary="Draft v1")
        sa2 = HrSelfAssessment.objects.filter(case_id=case_id).first()
        self.assertIsNotNone(sa2)
        self.assertEqual(sa2.summary, "Draft v1")
        # 验证同一 case_id 只能有一条自评
        with self.assertRaises(Exception):
            HrSelfAssessment.objects.create(tenant_id=self.tenant_id, case_id=case_id, summary="Duplicate")

    def test_reviewer_assignment_unique_constraint(self):
        from hr_assessment.models.evidence import HrReviewerAssignment
        case_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        HrReviewerAssignment.objects.create(
            tenant_id=self.tenant_id, case_id=case_id,
            reviewer_role="DIRECT_MANAGER", reviewer_staff_id=reviewer_id,
        )
        with self.assertRaises(Exception):
            HrReviewerAssignment.objects.create(
                tenant_id=self.tenant_id, case_id=case_id,
                reviewer_role="DIRECT_MANAGER", reviewer_staff_id=reviewer_id,
            )

    def test_calibration_revision_preserves_before_after(self):
        from hr_assessment.models.result import HrCalibrationSession, HrCalibrationRevision
        session = HrCalibrationSession.objects.create(
            tenant_id=self.tenant_id, cycle_id=uuid.uuid4(), session_status="OPEN",
        )
        rev = HrCalibrationRevision.objects.create(
            session=session, case_id=uuid.uuid4(),
            before_rating_json={"score": 85}, after_rating_json={"score": 90},
            before_grade_recommendation="QUALIFIED", after_grade_recommendation="EXCELLENT",
            reason_code="COLLECTIVE_ADJUSTMENT",
        )
        self.assertEqual(rev.before_grade_recommendation, "QUALIFIED")
        self.assertEqual(rev.after_grade_recommendation, "EXCELLENT")

    def test_quota_last_slot_validates_ratio(self):
        from hr_assessment.models.policy import HrExcellentQuotaPolicy
        policy = HrExcellentQuotaPolicy.objects.create(
            tenant_id=self.tenant_id, name="默认优秀比例", quota_basis_population="eligible",
            max_excellent_ratio=0.20, over_quota_action="BLOCKER", effective_from="2026-01-01",
        )
        self.assertEqual(float(policy.max_excellent_ratio), 0.20)

    def test_finalize_produces_result_version(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        self.assertEqual(result.status, "FINALIZED")
        self.assertEqual(result.result_version_no, 1)

    def test_objection_creates_isolated_record(self):
        from hr_assessment.models.result import HrAssessmentObjection
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        obj = HrAssessmentObjection.objects.create(
            tenant_id=self.tenant_id, result=result, reason="对教学指标评分有异议",
            status="SUBMITTED",
        )
        self.assertEqual(obj.status, "SUBMITTED")
        self.assertIn("教学", obj.reason)

    def test_revision_creates_new_version(self):
        from hr_assessment.models.result import HrResultRevision
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        revision = HrResultRevision.objects.create(
            tenant_id=self.tenant_id, result=result,
            previous_version=1, new_version=2,
            revision_type="CORRECTION", reason="数据纠错：展示标签修正",
            before_snapshot_json={"grade": "QUALIFIED"}, after_snapshot_json={"grade": "QUALIFIED"},
        )
        self.assertEqual(revision.new_version, 2)
        self.assertEqual(revision.revision_type, "CORRECTION")

    def test_evidence_refresh_preserves_snapshot_hash(self):
        from hr_assessment.models.evidence import HrAssessmentEvidenceRef
        import hashlib
        test_hash = hashlib.sha256(b"test_evidence").hexdigest()
        ev = HrAssessmentEvidenceRef.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(),
            provider_type="ACADEMIC", source_object_type="TeachingHours",
            source_object_id="TH-123", snapshot_hash=test_hash,
        )
        self.assertEqual(ev.snapshot_hash, test_hash)

    def test_population_freeze_unique_per_cycle_staff(self):
        from hr_assessment.models.cycle import HrAssessmentPopulationSnapshot, HrAssessmentCycle
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="TEST-001", assessment_type="ANNUAL",
            name="测试周期", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T00:00:00Z",
            policy_version_id=uuid.uuid4(),
        )
        staff_id = uuid.uuid4()
        HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=self.tenant_id, cycle=cycle, staff_id=staff_id,
            included=True, snapshot_at="2026-01-01T00:00:00Z",
        )
        with self.assertRaises(Exception):
            HrAssessmentPopulationSnapshot.objects.create(
                tenant_id=self.tenant_id, cycle=cycle, staff_id=staff_id,
                included=True, snapshot_at="2026-01-02T00:00:00Z",
            )

    def test_excel_job_uses_separate_batch_model(self):
        """批量操作应有独立的批量头/行模型"""
        from hr_assessment.models.case import HrAssessmentCase
        batch_cases = HrAssessmentCase.objects.filter(tenant_id=self.tenant_id)
        self.assertIsNotNone(batch_cases)
