"""验证所有 HR12 模型/常量/Provider/Service 可正确导入。"""

from django.test import TestCase


class TestAllImports(TestCase):
    def test_constants_import(self):
        from hr_assessment.constants import (
            AssessmentType,
            PolicyStatus,
            CycleLifecycleStatus,
            AnnualGrade,
            TermGrade,
            TrustLevel,
            ReviewerRole,
            CaseStatus,
            ConflictStatus,
            AnonymityStrategy,
            JobClassificationCategory,
        )
        self.assertEqual(AssessmentType.ANNUAL, "ANNUAL")
        self.assertEqual(PolicyStatus.PUBLISHED, "PUBLISHED")
        self.assertEqual(AnnualGrade.EXCELLENT, "EXCELLENT")
        self.assertEqual(TermGrade.QUALIFIED, "QUALIFIED")

    def test_models_import(self):
        from hr_assessment.models.policy import (
            HrAssessmentPolicyPack,
            HrAssessmentPolicyVersion,
            HrRatingScaleVersion,
            HrIndicatorDefinition,
            HrIndicatorVersion,
            HrIndicatorSetVersion,
            HrIndicatorBinding,
            HrAssessmentWorkflowVersion,
            HrWorkflowStep,
            HrAssessmentClassificationProfileVersion,
            HrEvidenceRequirement,
            HrGateRule,
            HrGateRuleVersion,
            HrResultRuleVersion,
            HrExcellentQuotaPolicy,
        )
        self.assertTrue(issubclass(HrAssessmentPolicyPack, object))

    def test_models_cycle_import(self):
        from hr_assessment.models.cycle import (
            HrAssessmentCycle,
            HrCycleSnapshot,
            HrAssessmentPopulationSnapshot,
        )
        self.assertTrue(issubclass(HrAssessmentCycle, object))

    def test_models_goal_import(self):
        from hr_assessment.models.goal import (
            HrAssessmentGoalPlan,
            HrAssessmentGoal,
            HrGoalVersion,
            HrGoalMeasure,
            HrGoalAssignment,
            HrGoalProgressEvent,
            HrGoalCheckIn,
            HrRoutineAssessmentEntry,
        )
        self.assertTrue(issubclass(HrAssessmentGoalPlan, object))

    def test_models_evidence_import(self):
        from hr_assessment.models.evidence import (
            HrAssessmentEvidenceRef,
            HrMetricSnapshot,
            HrSelfAssessment,
            HrReviewerAssignment,
            HrReviewerEvaluation,
            HrQuestionnaireVersion,
            HrQuestionVersion,
            HrMultiRaterSession,
            HrMultiRaterFeedback,
        )
        self.assertTrue(issubclass(HrAssessmentEvidenceRef, object))

    def test_models_case_import(self):
        from hr_assessment.models.case import (
            HrSubjectSnapshot,
            HrAssessmentCase,
            HrAnnualAssessmentCase,
            HrTermAssessmentCase,
            HrSpecialAssessmentCase,
            HrEthicsAssessmentCase,
            HrAssessmentPublicityCase,
        )
        self.assertTrue(issubclass(HrSubjectSnapshot, object))

    def test_models_result_import(self):
        from hr_assessment.models.result import (
            HrCalibrationSession,
            HrCalibrationRevision,
            HrAssessmentDecisionSession,
            HrFinalAssessmentResult,
            HrResultNotice,
            HrAcknowledgement,
            HrAssessmentObjection,
            HrResultRevision,
            HrAssessmentArchivePackage,
            HrResultApplicationLedger,
        )
        self.assertTrue(issubclass(HrFinalAssessmentResult, object))

    def test_providers_import(self):
        from hr_assessment.providers.base import (
            BaseAssessmentProvider,
            ProviderContext,
            ProviderResult,
            ProviderStatus,
        )
        from hr_assessment.providers.interfaces import (
            PersonProvider,
            AgreementProvider,
            DevelopmentProvider,
            TimeSummaryProvider,
            PROVIDER_REGISTRY,
        )
        self.assertIn("person", PROVIDER_REGISTRY)
        self.assertIn("development", PROVIDER_REGISTRY)

    def test_service_import(self):
        from hr_assessment.service import PolicyPackService, PolicyVersionService, EligibilityResolver
        svc = PolicyPackService()
        self.assertIsNotNone(svc)

    def test_permissions_import(self):
        from hr_assessment.permissions import (
            ASSESSMENT_PERMISSIONS,
            DataScope,
            PERMISSION_SCOPE,
            SOD_CONFLICT_PAIRS,
        )
        self.assertEqual(len(ASSESSMENT_PERMISSIONS), 14)
        self.assertIn("hr.assessment.policy.admin", dict(ASSESSMENT_PERMISSIONS))
        self.assertIn("hr.assessment.employee_self", PERMISSION_SCOPE)
