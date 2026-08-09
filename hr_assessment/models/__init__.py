"""HR12 Assessment — Authority 模型层（生产级）。

全部 45 个模型 + Managers + Admin。
"""

# base
from hr_assessment.models.base import TenantScopedModel, VersionedModel, TenantManager  # noqa: F401
# policy (13 models)
from hr_assessment.models.policy import (  # noqa: F401
    PolicyPackManager, PolicyVersionManager,
    HrAssessmentPolicyPack, HrAssessmentPolicyVersion,
    HrRatingScaleVersion, HrIndicatorDefinition, HrIndicatorVersion,
    HrIndicatorSetVersion, HrAssessmentWorkflowVersion,
    HrAssessmentClassificationProfileVersion, HrEvidenceRequirement,
    HrGateRule, HrGateRuleVersion, HrResultRuleVersion, HrExcellentQuotaPolicy,
)
# cycle (3)
from hr_assessment.models.cycle import HrAssessmentCycle, HrCycleSnapshot, HrAssessmentPopulationSnapshot  # noqa: F401
# goal (8)
from hr_assessment.models.goal import (  # noqa: F401
    HrAssessmentGoalPlan, HrAssessmentGoal, HrGoalVersion, HrGoalMeasure,
    HrGoalAssignment, HrGoalProgressEvent, HrGoalCheckIn, HrRoutineAssessmentEntry,
)
# evidence (7)
from hr_assessment.models.evidence import (  # noqa: F401
    HrAssessmentEvidenceRef, HrMetricSnapshot, HrSelfAssessment,
    HrReviewerAssignment, HrReviewerEvaluation,
    HrQuestionnaireVersion, HrMultiRaterSession,
)
# case (6)
from hr_assessment.models.case import (  # noqa: F401
    HrSubjectSnapshot, HrAssessmentCase, HrAnnualAssessmentCase,
    HrTermAssessmentCase, HrSpecialAssessmentCase, HrEthicsAssessmentCase,
    HrAssessmentPublicityCase,
)
# result (9)
from hr_assessment.models.result import (  # noqa: F401
    HrCalibrationSession, HrCalibrationRevision, HrAssessmentDecisionSession,
    HrFinalAssessmentResult, HrResultNotice, HrAcknowledgement,
    HrAssessmentObjection, HrResultRevision, HrAssessmentArchivePackage,
    HrResultApplicationLedger,
)
