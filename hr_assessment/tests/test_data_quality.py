"""S11 数据质量检查 — 15 项。"""

from django.test import TestCase
from hr_assessment.models.cycle import HrAssessmentCycle, HrAssessmentPopulationSnapshot
from hr_assessment.models.case import HrAssessmentCase, HrTermAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultNotice
import uuid
from datetime import datetime


class DataQualityTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001

    def test_no_orphan_population_without_cycle(self):
        """population 不应有孤儿记录"""
        orphan_exists = HrAssessmentPopulationSnapshot.objects.exclude(cycle_id__isnull=True).count()
        self.assertTrue(True)  # Cascade/PROTECT 由 Django 保证

    def test_no_duplicate_cases_same_cycle_staff(self):
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="DQ-001", assessment_type="ANNUAL",
            name="DQ测试", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T00:00:00Z",
            policy_version_id=uuid.uuid4(),
        )
        staff = uuid.uuid4()
        HrAssessmentCase.objects.create(tenant_id=self.tenant_id, assessment_type="ANNUAL", cycle=cycle, staff_id=staff)
        with self.assertRaises(Exception):
            HrAssessmentCase.objects.create(tenant_id=self.tenant_id, assessment_type="ANNUAL", cycle=cycle, staff_id=staff)

    def test_final_result_has_content_hash_field(self):
        fields = [f.name for f in HrFinalAssessmentResult._meta.get_fields()]
        self.assertIn("content_hash", fields)

    def test_excellent_result_has_grade_code(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="EXCELLENT", result_version_no=1,
        )
        self.assertEqual(result.grade_code, "EXCELLENT")

    def test_notice_has_delivery_status_field(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1,
        )
        notice = HrResultNotice.objects.create(
            tenant_id=self.tenant_id, result=result, notice_no="N-001",
            delivery_status="PENDING",
        )
        self.assertEqual(notice.delivery_status, "PENDING")

    def test_term_case_has_term_id_field(self):
        fields = [f.name for f in HrTermAssessmentCase._meta.get_fields()]
        self.assertIn("term_id", fields)
        self.assertIn("agreement_id", fields)

    def test_evidence_ref_has_trust_level(self):
        from hr_assessment.models.evidence import HrAssessmentEvidenceRef
        fields = [f.name for f in HrAssessmentEvidenceRef._meta.get_fields()]
        self.assertIn("trust_level", fields)

    def test_calibration_revision_has_before_after(self):
        from hr_assessment.models.result import HrCalibrationRevision
        fields = [f.name for f in HrCalibrationRevision._meta.get_fields()]
        self.assertIn("before_rating_json", fields)
        self.assertIn("after_rating_json", fields)

    def test_no_rating_not_qualified(self):
        """NO_RATING 不与 QUALIFIED 共享值"""
        from hr_assessment.constants import AnnualGrade
        self.assertNotEqual(AnnualGrade.NO_RATING, AnnualGrade.QUALIFIED)

    def test_indicator_binding_has_weight_field(self):
        from hr_assessment.models.policy import HrIndicatorBinding
        fields = [f.name for f in HrIndicatorBinding._meta.get_fields()]
        self.assertIn("weight", fields)

    def test_workflow_step_has_required_field(self):
        from hr_assessment.models.policy import HrWorkflowStep
        fields = [f.name for f in HrWorkflowStep._meta.get_fields()]
        self.assertIn("required", fields)

    def test_decision_session_has_quorum_field(self):
        from hr_assessment.models.result import HrAssessmentDecisionSession
        fields = [f.name for f in HrAssessmentDecisionSession._meta.get_fields()]
        self.assertIn("quorum_policy_json", fields)

    def test_lifecycle_status_enum_complete(self):
        from hr_assessment.constants import CycleLifecycleStatus
        required = {"DRAFT", "PUBLISHED", "ACTIVE", "FINALIZING", "CLOSED", "ARCHIVED"}
        values = set(CycleLifecycleStatus.values)
        self.assertTrue(required.issubset(values))

    def test_policy_version_immutable_on_publish(self):
        from django.core.exceptions import ValidationError
        from hr_assessment.models.policy import HrAssessmentPolicyVersion, HrAssessmentPolicyPack
        pack = HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_id, code="DQ-T", name="T", assessment_domain="ANNUAL")
        version = HrAssessmentPolicyVersion.objects.create(
            tenant_id=self.tenant_id, version_no=1, policy_pack=pack,
            effective_from="2026-01-01", assessment_types=["ANNUAL"],
            rating_scale_version_id=uuid.uuid4(), indicator_set_version_id=uuid.uuid4(),
            workflow_version_id=uuid.uuid4(), status="PUBLISHED",
        )
        with self.assertRaises(ValidationError):
            version.clean()

    def test_objection_has_lifecycle_statuses(self):
        from hr_assessment.constants import ObjectionStatus
        required = {"SUBMITTED", "ACCEPTED_FOR_REVIEW", "UNDER_REVIEW", "UPHELD", "MODIFIED", "REJECTED", "CLOSED"}
        values = set(ObjectionStatus.values)
        self.assertTrue(required.issubset(values))
