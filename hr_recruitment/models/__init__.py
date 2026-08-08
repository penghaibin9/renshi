"""
hr_recruitment.models —— HR04 权威领域模型包（S2）。

模型职责（《04_HR04_总册》§7 信息架构）：
  plan         → HR04-01 年度用人计划
  campaign     → HR04-02 招聘项目与岗位（含公告/资格/评分方案版本）
  candidate    → HR04-03 候选自然人与身份去重
  application  → HR04-03 应聘申请 + 状态迁移 ledger + 材料
  qualification→ HR04-04 资格审查
  assessment   → HR04-05 考试面试与考察（含评分/回避/体检/考察）
  offer        → HR04-06 拟录用/公示/异议/Offer/HR05 handoff
  audit        → HR04 专项审计

全表硬规则：所有权威表带 tenant_id；无 tenant 上下文 fail-closed（见 context.py）。
"""

from hr_recruitment.models.plan import (
    HrHiringPlanCycle,
    HrHiringPlanLine,
    HrHiringPlanRequest,
)
from hr_recruitment.models.campaign import (
    HrQualificationRuleSetVersion,
    HrRecruitmentAnnouncementVersion,
    HrRecruitmentCampaign,
    HrRecruitmentPosition,
    HrSelectionSchemeVersion,
)
from hr_recruitment.models.candidate import (
    HrCandidateIdentityMatch,
    HrRecruitmentCandidate,
)
from hr_recruitment.models.application import (
    HrApplicationMaterial,
    HrApplicationTransition,
    HrJobApplication,
)
from hr_recruitment.models.qualification import (
    HrQualificationDecision,
    HrQualificationReview,
    HrQualificationRule,
)
from hr_recruitment.models.assessment import (
    HrAssessmentEvent,
    HrBackgroundCheck,
    HrCandidateScore,
    HrCandidateScoreSheet,
    HrEvaluatorAssignment,
    HrMedicalCheck,
    HrScoreCriterion,
    HrScoreSheetTemplate,
    HrSelectionComponent,
    HrSelectionResultSnapshot,
)
from hr_recruitment.models.offer import (
    HrNoticeObjection,
    HrProposedHire,
    HrPublicNotice,
    HrPublicNoticeEntry,
    HrRecruitmentHandoff,
    HrRecruitmentOffer,
)
from hr_recruitment.models.audit import (
    HrRecruitmentAuditEvent,
    HrSensitiveCandidateAccessLog,
)

__all__ = [
    "HrHiringPlanCycle",
    "HrHiringPlanRequest",
    "HrHiringPlanLine",
    "HrRecruitmentCampaign",
    "HrRecruitmentPosition",
    "HrRecruitmentAnnouncementVersion",
    "HrQualificationRuleSetVersion",
    "HrSelectionSchemeVersion",
    "HrRecruitmentCandidate",
    "HrCandidateIdentityMatch",
    "HrJobApplication",
    "HrApplicationTransition",
    "HrApplicationMaterial",
    "HrQualificationRule",
    "HrQualificationReview",
    "HrQualificationDecision",
    "HrSelectionComponent",
    "HrAssessmentEvent",
    "HrEvaluatorAssignment",
    "HrScoreSheetTemplate",
    "HrScoreCriterion",
    "HrCandidateScoreSheet",
    "HrCandidateScore",
    "HrSelectionResultSnapshot",
    "HrMedicalCheck",
    "HrBackgroundCheck",
    "HrProposedHire",
    "HrPublicNotice",
    "HrPublicNoticeEntry",
    "HrNoticeObjection",
    "HrRecruitmentOffer",
    "HrRecruitmentHandoff",
    "HrRecruitmentAuditEvent",
    "HrSensitiveCandidateAccessLog",
]
