import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentCycle,
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
    HrCycleSnapshot,
    HrResultRuleVersion,
    HrReviewerAssignment,
    HrReviewerEvaluation,
)
from hr_assessment.services.finalization_service import (
    AssessmentFinalizationError,
    AssessmentFinalizationService,
)


class AssessmentScoreCalculationAuthorityTests(TestCase):
    tenant_id = 77

    def setUp(self):
        now = timezone.now()
        self.result_rule = HrResultRuleVersion.objects.create(
            tenant_id=self.tenant_id,
            name="年度结果映射",
            version_no=1,
            status="PUBLISHED",
            score_to_grade_mapping={
                "bands": [
                    {
                        "gradeCode": "EXCELLENT",
                        "minScore": "90",
                        "maxScore": "100",
                        "displayGrade": {"zh-CN": "优秀"},
                    },
                    {
                        "gradeCode": "QUALIFIED",
                        "minScore": "60",
                        "maxScore": "89.99",
                        "displayGrade": {"zh-CN": "合格"},
                    },
                    {
                        "gradeCode": "UNQUALIFIED",
                        "minScore": "0",
                        "maxScore": "59.99",
                        "displayGrade": {"zh-CN": "不合格"},
                    },
                ]
            },
        )
        pack = HrAssessmentPolicyPack.objects.create(
            tenant_id=self.tenant_id,
            code="APPOINTMENT-ASSESS",
            name="竞聘评价政策",
            assessment_domain="APPOINTMENT",
        )
        self.policy = HrAssessmentPolicyVersion.objects.create(
            tenant_id=self.tenant_id,
            policy_pack=pack,
            version_no=1,
            status="PUBLISHED",
            effective_from=(now - timedelta(days=30)).date(),
            assessment_types=["COMPETITIVE_APPOINTMENT"],
            rating_scale_version_id=uuid.uuid4(),
            indicator_set_version_id=uuid.uuid4(),
            workflow_version_id=uuid.uuid4(),
            result_rule_version_id=self.result_rule.id,
        )
        self.cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id,
            cycle_no=f"ASSESS-{uuid.uuid4().hex[:8]}",
            assessment_type="COMPETITIVE_APPOINTMENT",
            name="竞聘评价",
            start_at=now - timedelta(days=5),
            end_at=now,
            policy_version_id=self.policy.id,
            lifecycle_status="REVIEWING",
        )
        HrCycleSnapshot.objects.create(
            tenant_id=self.tenant_id,
            cycle=self.cycle,
            frozen_policy_json={
                "id": str(self.policy.id),
                "contentHash": self.policy.content_hash,
                "resultRule": {
                    "id": str(self.result_rule.id),
                    "contentHash": self.result_rule.content_hash,
                    "scoreToGradeMapping": self.result_rule.score_to_grade_mapping,
                }
            },
            frozen_reviewer_rules_json={
                "scoreAggregation": "WEIGHTED_AVERAGE",
                "scoreField": "totalScore",
                "roleWeights": {"CHAIR": "2", "MEMBER": "1"},
            },
            frozen_rating_scale_json={"minValue": "0", "maxValue": "100"},
        )
        self.case = HrAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type="COMPETITIVE_APPOINTMENT",
            cycle=self.cycle,
            staff_id=uuid.uuid4(),
            policy_version_id=self.policy.id,
            status="PROPOSED",
        )

    def _evaluation(self, role, score, *, tenant_id=None):
        assignment = HrReviewerAssignment.objects.create(
            tenant_id=self.tenant_id,
            case_id=self.case.id,
            reviewer_role=role,
            reviewer_staff_id=uuid.uuid4(),
            status="SUBMITTED",
        )
        return HrReviewerEvaluation.objects.create(
            tenant_id=tenant_id or self.tenant_id,
            assignment=assignment,
            rating_json={"totalScore": score},
            submitted_at=timezone.now(),
            revision_no=1,
        )

    def test_weighted_score_and_grade_are_server_derived(self):
        chair = self._evaluation("CHAIR", "90")
        member = self._evaluation("MEMBER", "60")

        calculated = AssessmentFinalizationService(self.tenant_id)._calculate_result(
            case=self.case
        )

        self.assertEqual(calculated.calculated_score, Decimal("80.00"))
        self.assertEqual(calculated.grade_code, "QUALIFIED")
        self.assertEqual(calculated.display_grade_snapshot, {"zh-CN": "合格"})
        self.assertEqual(
            {item["evaluationId"] for item in calculated.calculation_snapshot["contributions"]},
            {str(chair.id), str(member.id)},
        )

    def test_cross_tenant_evaluation_does_not_satisfy_submission(self):
        self._evaluation("CHAIR", "100", tenant_id=88)

        with self.assertRaises(AssessmentFinalizationError) as ctx:
            AssessmentFinalizationService(self.tenant_id)._calculate_result(case=self.case)

        self.assertEqual(ctx.exception.code, "ASSESSMENT_REVIEWER_SUBMISSION_MISSING")
