"""
hr10_development/events/registry.py

HR10 事件注册表（对齐 00 §28.3）。

每个事件冻结：eventType / eventVersion / owner / consumers / aggregate
/ tenant / effectiveAt / payload schema / PII classification / idempotency / replay rule。
"""

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class EventSpec:
    event_type: str
    event_version: int
    owner: str
    consumers: list[str]
    aggregate_type: str
    payload_pii: str  # NONE / PII_SCRUBBED / CONTAINS_PII
    idempotency_key: str


# ============================================================
# S9 冻结：28 事件规格
# ============================================================

class DevelopmentEventRegistry:
    """HR10 事件注册中心。"""

    events: ClassVar[list[EventSpec]] = [
        # Plans
        EventSpec("DevelopmentPlanPublished", 1, "HR10-01", ["HR01", "HR18"], "HrDevelopmentPlan", "NONE", "plan_id+version_id"),
        EventSpec("DevelopmentNeedCreated", 1, "HR10-01", ["HR01"], "HrDevelopmentNeed", "PII_SCRUBBED", "need_id"),
        # Programs
        EventSpec("LearningProgramPublished", 1, "HR10-02", ["HR01", "HR17"], "HrLearningProgram", "NONE", "program_id+version_id"),
        EventSpec("LearningOfferingOpened", 1, "HR10-02", ["HR17"], "HrLearningOffering", "NONE", "offering_id"),
        # Training Requests
        EventSpec("TrainingRequestSubmitted", 1, "HR10-03", ["approvers"], "HrTrainingRequest", "PII_SCRUBBED", "request_id"),
        EventSpec("TrainingRequestApproved", 1, "HR10-03", ["HR11", "HR15"], "HrTrainingRequest", "PII_SCRUBBED", "request_id"),
        EventSpec("TrainingRequestReturned", 1, "HR10-03", ["applicant"], "HrTrainingRequest", "NONE", "request_id"),
        EventSpec("TrainingRequestRejected", 1, "HR10-03", ["applicant"], "HrTrainingRequest", "NONE", "request_id"),
        # Enrollment
        EventSpec("LearningEnrollmentCreated", 1, "HR10-03", ["HR11", "HR17"], "HrLearningEnrollment", "PII_SCRUBBED", "enrollment_id"),
        EventSpec("LearningWaitlisted", 1, "HR10-03", ["HR17"], "HrLearningEnrollment", "NONE", "enrollment_id"),
        EventSpec("LearningStarted", 1, "HR10-03", ["HR11"], "HrLearningEnrollment", "NONE", "enrollment_id"),
        # Completion
        EventSpec("LearningCompletionSubmitted", 1, "HR10-05", ["verifiers"], "HrLearningCompletion", "NONE", "completion_id"),
        EventSpec("LearningCompletionVerified", 1, "HR10-05", ["HR09", "HR12"], "HrLearningCompletion", "NONE", "completion_id"),
        # Further Study
        EventSpec("FurtherStudyStarted", 1, "HR10-03", ["HR03", "HR11"], "HrFurtherStudyCase", "PII_SCRUBBED", "case_id"),
        EventSpec("FurtherStudyMilestoneVerified", 1, "HR10-03", ["HR03"], "HrFurtherStudyMilestone", "PII_SCRUBBED", "milestone_id"),
        # Practice
        EventSpec("PracticeProjectPublished", 1, "HR10-04", ["HR01"], "HrEnterprisePracticeProject", "NONE", "project_id+version_id"),
        EventSpec("PracticeAssignmentCreated", 1, "HR10-04", ["HR11", "mentor"], "HrEnterprisePracticeAssignment", "PII_SCRUBBED", "assignment_id"),
        EventSpec("PracticeAssignmentStarted", 1, "HR10-04", ["HR11"], "HrEnterprisePracticeAssignment", "NONE", "assignment_id"),
        EventSpec("PracticeAssignmentSuspended", 1, "HR10-05", ["HR11"], "HrEnterprisePracticeAssignment", "NONE", "assignment_id"),
        EventSpec("PracticeAssignmentResumed", 1, "HR10-05", ["HR11"], "HrEnterprisePracticeAssignment", "NONE", "assignment_id"),
        EventSpec("PracticeAssignmentTransferred", 1, "HR10-05", ["HR11"], "HrEnterprisePracticeAssignment", "PII_SCRUBBED", "assignment_id"),
        EventSpec("PracticeEvidenceSubmitted", 1, "HR10-05", ["evaluators"], "HrEnterprisePracticeEvidence", "CONTAINS_PII", "evidence_id"),
        EventSpec("PracticeEvaluationFinalized", 1, "HR10-05", ["HR09", "HR12", "HR15"], "HrEnterprisePracticeEvaluation", "NONE", "assignment_id"),
        EventSpec("DevelopmentOutputVerified", 1, "HR10-05", ["Academic", "Research"], "HrDevelopmentOutput", "NONE", "output_id"),
        # Facts (00 §28.3 canonical)
        EventSpec("DevelopmentFactVerified", 1, "HR10-06", ["HR09", "HR12", "HR06"], "HrDevelopmentFact", "NONE", "fact_id"),
        EventSpec("DevelopmentFactSuperseded", 1, "HR10-06", ["HR09", "HR12"], "HrDevelopmentFact", "NONE", "fact_id"),
        # Risk
        EventSpec("DevelopmentRiskOpened", 1, "HR10-06", ["HR01", "manager"], "HrDevelopmentRiskCase", "PII_SCRUBBED", "risk_id"),
        EventSpec("DevelopmentRiskResolved", 1, "HR10-06", ["HR01", "manager"], "HrDevelopmentRiskCase", "PII_SCRUBBED", "risk_id"),
    ]

    @classmethod
    def get_by_type(cls, event_type: str) -> EventSpec | None:
        for spec in cls.events:
            if spec.event_type == event_type:
                return spec
        return None

    @classmethod
    def all_types(cls) -> list[str]:
        return [e.event_type for e in cls.events]
