"""
hr_recruitment/constants.py

HR04 冻结枚举（《04_HR04_招聘与人才引进_施工总册_终极版》第 8.4/9.4/9.5/10.3/12.3-12.8/13.3-13.6/14.1 节）。

原则：
- canonical status 是系统权威，学校不允许随便创建（总册 14.2）。
- WorkflowStage 是展示/工作队列阶段，可配置；与 canonical status 分离。
- 所有枚举为 Django TextChoices，迁移期冻结值，禁止在正式版本中删除值（additive-only）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ApplicationCanonicalStatus(models.TextChoices):
    """HrJobApplication 权威状态机（总册 14.1 冻结）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    RETURNED = "RETURNED", _("Returned")
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    QUALIFIED = "QUALIFIED", _("Qualified")
    DISQUALIFIED = "DISQUALIFIED", _("Disqualified")
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING", _("Assessment Pending")
    ASSESSING = "ASSESSING", _("Assessing")
    ASSESSMENT_PASSED = "ASSESSMENT_PASSED", _("Assessment Passed")
    ASSESSMENT_FAILED = "ASSESSMENT_FAILED", _("Assessment Failed")
    MEDICAL_PENDING = "MEDICAL_PENDING", _("Medical Pending")
    MEDICAL_REVIEW = "MEDICAL_REVIEW", _("Medical Review")
    BACKGROUND_PENDING = "BACKGROUND_PENDING", _("Background Pending")
    BACKGROUND_REVIEW = "BACKGROUND_REVIEW", _("Background Review")
    PROPOSED_HIRE = "PROPOSED_HIRE", _("Proposed Hire")
    PUBLIC_NOTICE = "PUBLIC_NOTICE", _("Public Notice")
    OFFER_PENDING = "OFFER_PENDING", _("Offer Pending")
    OFFERED = "OFFERED", _("Offered")
    OFFER_ACCEPTED = "OFFER_ACCEPTED", _("Offer Accepted")
    OFFER_DECLINED = "OFFER_DECLINED", _("Offer Declined")
    HANDOFF_TO_HR05 = "HANDOFF_TO_HR05", _("Handoff To HR05")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    CANCELLED = "CANCELLED", _("Cancelled")


class CampaignStatus(models.TextChoices):
    """HrRecruitmentCampaign 状态机（总册 9.4）。"""

    DRAFT = "DRAFT", _("Draft")
    UNDER_APPROVAL = "UNDER_APPROVAL", _("Under Approval")
    APPROVED = "APPROVED", _("Approved")
    PUBLISHED = "PUBLISHED", _("Published")
    OPEN = "OPEN", _("Open")
    CLOSED = "CLOSED", _("Closed")
    RESULT_PROCESSING = "RESULT_PROCESSING", _("Result Processing")
    COMPLETED = "COMPLETED", _("Completed")
    ARCHIVED = "ARCHIVED", _("Archived")


class RecruitmentPositionStatus(models.TextChoices):
    """HrRecruitmentPosition 状态机（总册 9.5）。"""

    DRAFT = "DRAFT", _("Draft")
    READY = "READY", _("Ready")
    OPEN = "OPEN", _("Open")
    CLOSED = "CLOSED", _("Closed")
    SELECTION = "SELECTION", _("Selection")
    PROPOSED_HIRE = "PROPOSED_HIRE", _("Proposed Hire")
    FILLED = "FILLED", _("Filled")
    PARTIALLY_FILLED = "PARTIALLY_FILLED", _("Partially Filled")
    CANCELLED = "CANCELLED", _("Cancelled")


class PlanCycleStatus(models.TextChoices):
    """HrHiringPlanCycle 状态（总册 8.4 的周期级）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_HR_REVIEW = "UNDER_HR_REVIEW", _("Under HR Review")
    RETURNED = "RETURNED", _("Returned")
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    UNDER_SCHOOL_APPROVAL = "UNDER_SCHOOL_APPROVAL", _("Under School Approval")
    APPROVED = "APPROVED", _("Approved")
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
    REJECTED = "REJECTED", _("Rejected")
    CLOSED = "CLOSED", _("Closed")


class PlanRequestStatus(models.TextChoices):
    """HrHiringPlanRequest 状态（同 8.4；RETURNED≠REJECTED）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_HR_REVIEW = "UNDER_HR_REVIEW", _("Under HR Review")
    RETURNED = "RETURNED", _("Returned")
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    UNDER_SCHOOL_APPROVAL = "UNDER_SCHOOL_APPROVAL", _("Under School Approval")
    APPROVED = "APPROVED", _("Approved")
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
    REJECTED = "REJECTED", _("Rejected")
    CLOSED = "CLOSED", _("Closed")


class PlanLineStatus(models.TextChoices):
    """HrHiringPlanLine 行级状态。"""

    REQUESTED = "REQUESTED", _("Requested")
    APPROVED = "APPROVED", _("Approved")
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED", _("Partially Approved")
    REJECTED = "REJECTED", _("Rejected")
    IN_RECRUITMENT = "IN_RECRUITMENT", _("In Recruitment")
    FILLED = "FILLED", _("Filled")


class NeedType(models.TextChoices):
    """用人需求类型（总册 8.3）。"""

    NEW = "NEW", _("New")
    REPLACEMENT = "REPLACEMENT", _("Replacement")
    TALENT = "TALENT", _("Talent Introduction")
    TEMPORARY = "TEMPORARY", _("Temporary")


class CandidateStatus(models.TextChoices):
    """HrRecruitmentCandidate 状态（总册 10.3）。"""

    ACTIVE = "ACTIVE", _("Active")
    ANONYMIZED = "ANONYMIZED", _("Anonymized")
    BLOCKED = "BLOCKED", _("Blocked")


class IdentityMatchResult(models.TextChoices):
    """候选去重结果（总册 23）。"""

    EXACT_MATCH = "EXACT_MATCH", _("Exact Match")
    POSSIBLE_MATCH = "POSSIBLE_MATCH", _("Possible Match")
    NO_MATCH = "NO_MATCH", _("No Match")
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", _("Insufficient Data")


class MaterialType(models.TextChoices):
    """申请材料类型（总册 20）。"""

    RESUME = "RESUME", _("Resume")
    IDENTITY = "IDENTITY", _("Identity")
    DEGREE = "DEGREE", _("Degree Certificate")
    DIPLOMA = "DIPLOMA", _("Diploma")
    PROFESSIONAL_TITLE = "PROFESSIONAL_TITLE", _("Professional Title")
    TEACHER_QUALIFICATION = "TEACHER_QUALIFICATION", _("Teacher Qualification")
    SKILL_CERT = "SKILL_CERT", _("Skill Certificate")
    WORK_EXPERIENCE = "WORK_EXPERIENCE", _("Work Experience")
    ACHIEVEMENT = "ACHIEVEMENT", _("Representative Achievement")
    OTHER = "OTHER", _("Other")


class MaterialVerificationStatus(models.TextChoices):
    """材料核验状态。"""

    PENDING = "PENDING", _("Pending")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    SUPERSEDED = "SUPERSEDED", _("Superseded")


class SensitiveLevel(models.TextChoices):
    """材料敏感级（总册 22.2）。"""

    PUBLIC_HR = "PUBLIC_HR", _("Public HR")
    RESTRICTED_HR = "RESTRICTED_HR", _("Restricted HR")
    SENSITIVE = "SENSITIVE", _("Sensitive")
    HIGH_SENSITIVE = "HIGH_SENSITIVE", _("High Sensitive")


class RuleSeverity(models.TextChoices):
    """资格规则严重级（总册 11.2）。"""

    HARD = "HARD", _("Hard")
    SOFT = "SOFT", _("Soft")
    INFO = "INFO", _("Info")


class RuleSystemResult(models.TextChoices):
    """资格自动预检输出（总册 11.5）。"""

    PASS = "PASS", _("Pass")
    FAIL = "FAIL", _("Fail")
    DATA_MISSING = "DATA_MISSING", _("Data Missing")
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW", _("Needs Manual Review")
    NOT_APPLICABLE = "NOT_APPLICABLE", _("Not Applicable")


class QualificationDecisionType(models.TextChoices):
    """资格审查最终决策（总册 3.2/4.5）。"""

    QUALIFIED = "QUALIFIED", _("Qualified")
    RETURNED = "RETURNED", _("Returned")
    DISQUALIFIED = "DISQUALIFIED", _("Disqualified")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    REOPEN_OVERRIDDEN = "REOPEN_OVERRIDDEN", _("Reopen Overridden")


class SchemeStatus(models.TextChoices):
    """资格规则/评分方案版本状态。"""

    DRAFT = "DRAFT", _("Draft")
    LOCKED = "LOCKED", _("Locked")
    ACTIVE = "ACTIVE", _("Active")
    SUPERSEDED = "SUPERSEDED", _("Superseded")


class SelectionComponentType(models.TextChoices):
    """选拔组件类型（总册 3.1/12.2）。"""

    DOCUMENT_REVIEW = "DOCUMENT_REVIEW", _("Document Review")
    WRITTEN_EXAM = "WRITTEN_EXAM", _("Written Exam")
    TEACHING_DEMO = "TEACHING_DEMO", _("Teaching Demo")
    PROFESSIONAL_TEST = "PROFESSIONAL_TEST", _("Professional Test")
    SKILL_TEST = "SKILL_TEST", _("Skill Test")
    INTERVIEW = "INTERVIEW", _("Interview")
    PSYCHOLOGICAL_TEST = "PSYCHOLOGICAL_TEST", _("Psychological Test")
    MEDICAL_CHECK = "MEDICAL_CHECK", _("Medical Check")
    BACKGROUND_CHECK = "BACKGROUND_CHECK", _("Background Check")


class AssessmentMode(models.TextChoices):
    """考核场次模式（总册 12.3）。"""

    ONSITE = "ONSITE", _("Onsite")
    ONLINE = "ONLINE", _("Online")


class AssessmentEventStatus(models.TextChoices):
    """考核场次状态。"""

    DRAFT = "DRAFT", _("Draft")
    SCHEDULED = "SCHEDULED", _("Scheduled")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    COMPLETED = "COMPLETED", _("Completed")
    CANCELLED = "CANCELLED", _("Cancelled")


class ConflictStatus(models.TextChoices):
    """专家利益冲突状态（总册 12.6）。"""

    CLEAR = "CLEAR", _("Clear")
    DECLARED = "DECLARED", _("Declared")
    DETECTED = "DETECTED", _("Detected")
    RECUSED = "RECUSED", _("Recused")
    OVERRIDDEN = "OVERRIDDEN", _("Overridden")


class ScoreSheetStatus(models.TextChoices):
    """评分表状态（总册 12.4/12.7）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    LOCKED = "LOCKED", _("Locked")
    VOID = "VOID", _("Void")
    REOPEN_REQUESTED = "REOPEN_REQUESTED", _("Reopen Requested")
    REOPEN_APPROVED = "REOPEN_APPROVED", _("Reopen Approved")


class MedicalCheckStatus(models.TextChoices):
    """体检结论（总册 12.8）。"""

    PENDING = "PENDING", _("Pending")
    FIT = "FIT", _("Fit")
    UNFIT = "UNFIT", _("Unfit")
    RECHECK = "RECHECK", _("Recheck")
    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")


class BackgroundCheckStatus(models.TextChoices):
    """考察/政审结论（总册 12.8）。"""

    PENDING = "PENDING", _("Pending")
    PASS = "PASS", _("Pass")
    FAIL = "FAIL", _("Fail")
    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")


class ProposedHireDecision(models.TextChoices):
    """拟录用决策。"""

    PROPOSE = "PROPOSE", _("Propose")
    APPROVE = "APPROVE", _("Approve")
    REJECT = "REJECT", _("Reject")
    WITHDRAW = "WITHDRAW", _("Withdraw")


class PublicNoticeStatus(models.TextChoices):
    """公示状态（总册 13.4）。"""

    DRAFT = "DRAFT", _("Draft")
    PUBLISHED = "PUBLISHED", _("Published")
    ACTIVE = "ACTIVE", _("Active")
    CLOSED_NO_BLOCKER = "CLOSED_NO_BLOCKER", _("Closed No Blocker")
    CLOSED_WITH_OBJECTION = "CLOSED_WITH_OBJECTION", _("Closed With Objection")
    CANCELLED = "CANCELLED", _("Cancelled")


class ObjectionStatus(models.TextChoices):
    """公示异议案件状态（总册 13.5）。"""

    RECEIVED = "RECEIVED", _("Received")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE", _("Needs Evidence")
    RESOLVED_UPHOLD = "RESOLVED_UPHOLD", _("Resolved Uphold")
    RESOLVED_CHANGE = "RESOLVED_CHANGE", _("Resolved Change")
    CLOSED = "CLOSED", _("Closed")


class OfferStatus(models.TextChoices):
    """Offer 状态（总册 13.6）。"""

    DRAFT = "DRAFT", _("Draft")
    APPROVED = "APPROVED", _("Approved")
    ISSUED = "ISSUED", _("Issued")
    VIEWED = "VIEWED", _("Viewed")
    ACCEPTED = "ACCEPTED", _("Accepted")
    DECLINED = "DECLINED", _("Declined")
    EXPIRED = "EXPIRED", _("Expired")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")


class ReservationStatus(models.TextChoices):
    """HR02 岗位预占状态（总册 9.6/HR02 50.1）。"""

    HELD = "HELD", _("Held")
    COMMITTED = "COMMITTED", _("Committed")
    RELEASED = "RELEASED", _("Released")
    EXPIRED = "EXPIRED", _("Expired")
    CANCELLED = "CANCELLED", _("Cancelled")


class ApplicationSourceChannel(models.TextChoices):
    """申请来源渠道。"""

    PUBLIC_PORTAL = "PUBLIC_PORTAL", _("Public Portal")
    ADMIN_CREATED = "ADMIN_CREATED", _("Admin Created")
    LEGACY_MIGRATION = "LEGACY_MIGRATION", _("Legacy Migration")
    TALENT_POOL = "TALENT_POOL", _("Talent Pool")
    OTHER = "OTHER", _("Other")


class CampaignType(models.TextChoices):
    """招聘项目类型（总册 9.3）。"""

    SINGLE_POSITION = "SINGLE_POSITION", _("Single Position")
    MULTI_POSITION = "MULTI_POSITION", _("Multi Position")
    HIGH_LEVEL_TALENT = "HIGH_LEVEL_TALENT", _("High Level Talent")
    DOCTORAL_SPECIAL = "DOCTORAL_SPECIAL", _("Doctoral Special")
    EXTERNAL_EMPLOY = "EXTERNAL_EMPLOY", _("External Employ")


class AuthorityMode(models.TextChoices):
    """HR04 数据权威模式（总册 29）。"""

    LEGACY_RECRUITING_ONLY = "LEGACY_RECRUITING_ONLY", _("Legacy Recruiting Only")
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
    HR04_AUTHORITY = "HR04_AUTHORITY", _("HR04 Authority")


class HandoffStatus(models.TextChoices):
    """HR05 handoff 状态。"""

    CREATED = "CREATED", _("Created")
    FAILED = "FAILED", _("Failed")
