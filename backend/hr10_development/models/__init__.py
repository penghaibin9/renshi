"""
hr10_development/models/__init__.py
"""

from .base import DevelopmentTenantModel
from .catalog import DevelopmentActivityCatalog
from .provider_org import HrDevelopmentProviderOrganization
from .audit import HrDevelopmentAuditEvent
from .outbox import HrDevelopmentOutboxEvent
from .plan import HrDevelopmentPlan
from .plan_version import HrDevelopmentPlanVersion
from .need import HrDevelopmentNeed
from .target import HrDevelopmentTarget
from .budget import HrDevelopmentBudgetPlan
from .learning_program import HrLearningProgram
from .program_version import HrLearningProgramVersion
from .offering import HrLearningOffering
from .session import HrLearningSession
from .instructor import ProgramInstructorRef
from .training_request import HrTrainingRequest
from .enrollment import HrLearningEnrollment
from .approval_snapshot import HrDevelopmentApprovalSnapshot
from .participation import HrLearningParticipation
from .learning_completion import HrLearningCompletion
from .further_study import HrFurtherStudyCase, HrFurtherStudyMilestone
from .practice_project import HrEnterprisePracticeProject, HrEnterprisePracticeProjectVersion
from .practice_models import (
    HrPracticePositionScene, HrEnterprisePracticePlacement,
    HrEnterprisePracticeAssignment, HrEnterprisePracticeMentor,
    HrEnterprisePracticePlan,
)
from .practice_process import (
    HrEnterprisePracticeActivity, HrEnterprisePracticeEvidence,
    HrEnterpriseMentorFeedback, HrPracticeSchoolEvaluation,
    HrEnterprisePracticeEvaluation, HrDevelopmentOutput,
)
from .practice_attendance import HrEnterprisePracticeAttendanceFact
from .duration_ledger import HrDurationLedger
from .development_fact import (
    HrDevelopmentFact, HrDevelopmentMetricLedger,
    HrDevelopmentComplianceRule, HrDevelopmentRiskCase,
)

# Legacy takeover models are still part of the HR10 data migration contract.
# Import them explicitly so Django's migration state does not mistake the
# staging/import tables for abandoned models and propose destructive drops.
from hr10_development.legacy.import_job import HrDevelopmentImportJob
from hr10_development.legacy.staging import HrDevelopmentStagingRow

__all__ = [
    "DevelopmentTenantModel",
    "DevelopmentActivityCatalog",
    "HrDevelopmentProviderOrganization",
    "HrDevelopmentAuditEvent",
    "HrDevelopmentOutboxEvent",
    "HrDevelopmentPlan",
    "HrDevelopmentPlanVersion",
    "HrDevelopmentNeed",
    "HrDevelopmentTarget",
    "HrDevelopmentBudgetPlan",
    "HrLearningProgram",
    "HrLearningProgramVersion",
    "HrLearningOffering",
    "HrLearningSession",
    "ProgramInstructorRef",
    "HrTrainingRequest",
    "HrLearningEnrollment",
    "HrDevelopmentApprovalSnapshot",
    "HrLearningParticipation",
    "HrLearningCompletion",
    "HrFurtherStudyCase",
    "HrFurtherStudyMilestone",
    "HrEnterprisePracticeProject",
    "HrEnterprisePracticeProjectVersion",
    "HrPracticePositionScene",
    "HrEnterprisePracticePlacement",
    "HrEnterprisePracticeAssignment",
    "HrEnterprisePracticeMentor",
    "HrEnterprisePracticePlan",
    "HrEnterprisePracticeActivity",
    "HrEnterprisePracticeEvidence",
    "HrEnterpriseMentorFeedback",
    "HrPracticeSchoolEvaluation",
    "HrEnterprisePracticeEvaluation",
    "HrDevelopmentOutput",
    "HrEnterprisePracticeAttendanceFact",
    "HrDurationLedger",
    "HrDevelopmentFact",
    "HrDevelopmentMetricLedger",
    "HrDevelopmentComplianceRule",
    "HrDevelopmentRiskCase",
    "HrDevelopmentImportJob",
    "HrDevelopmentStagingRow",
]
