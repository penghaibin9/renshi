"""
hr_external/constants.py —— HR08 公共合同常量（S1 冻结）。

对齐总册《08_HR08_兼职外聘教师_施工总册_终极版》：
- §5 外聘分类体系（ExternalWorkerCategory）
- §20 Engagement 状态机
- §22 Assignment 类型
- §25 候选池状态
- §26 External Identity Match
- §34 Hiring 状态
- §36 伦理审查状态 / §37 冲突声明状态
- §47 Task 状态 / §56 Task Acceptance
- §50 Evidence / §51 Workload source
- §60 Renewal Decision / §65 Exit 状态 / §64 Exit 原因
- §66-67 AccessGrant / §93 Agreement Requirement / §95 账号生命周期
- §103 Outbox 事件 / §106 Risk / §107 Severity
- §87 错误码 / §88 权限码 / §89 Data Scope / §138 自纠错

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# ---------------------------------------------------------------------------
# 外聘类别（§5 / §18）
# ---------------------------------------------------------------------------
class ExternalWorkerCategory(models.TextChoices):
    """内置可扩展外聘类别。Title ≠ Engagement ≠ Assignment。"""

    PART_TIME_TEACHER = "PART_TIME_TEACHER", _("Part-time Teacher")
    EXTERNAL_TEACHER = "EXTERNAL_TEACHER", _("External Teacher")
    INDUSTRY_ADJUNCT = "INDUSTRY_ADJUNCT", _("Industry Adjunct")
    INDUSTRY_PROFESSOR = "INDUSTRY_PROFESSOR", _("Industry Professor")
    SKILL_MASTER = "SKILL_MASTER", _("Skill Master")
    INDUSTRY_MENTOR = "INDUSTRY_MENTOR", _("Industry Mentor")
    VISITING_PROFESSOR = "VISITING_PROFESSOR", _("Visiting Professor")
    GUEST_PROFESSOR = "GUEST_PROFESSOR", _("Guest Professor")
    HONORARY_TITLE = "HONORARY_TITLE", _("Honorary Title")
    EXTERNAL_EXPERT = "EXTERNAL_EXPERT", _("External Expert")
    PRACTICE_INSTRUCTOR = "PRACTICE_INSTRUCTOR", _("Practice Instructor")
    RETIRED_REHIRE_EXTERNAL = "RETIRED_REHIRE_EXTERNAL", _("Retired Rehire External")
    PROJECT_EXPERT = "PROJECT_EXPERT", _("Project Expert")
    OTHER = "OTHER", _("Other")


class CandidatePoolStatus(models.TextChoices):
    """候选池状态（§25）。DO_NOT_ENGAGE 为敏感业务结论。"""

    AVAILABLE = "AVAILABLE", _("Available")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    ENGAGED = "ENGAGED", _("Engaged")
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE", _("Temporarily Unavailable")
    DO_NOT_ENGAGE = "DO_NOT_ENGAGE", _("Do Not Engage")
    ARCHIVED = "ARCHIVED", _("Archived")


class TalentTagSource(models.TextChoices):
    """人才标签可信来源（§24.5）。"""

    SYSTEM_VERIFIED = "SYSTEM_VERIFIED", _("System Verified")
    HR_MANAGED = "HR_MANAGED", _("HR Managed")
    COLLEGE_TAG = "COLLEGE_TAG", _("College Tag")
    SELF_REPORTED = "SELF_REPORTED", _("Self Reported")


class IdentityMatchLevel(models.TextChoices):
    """同 tenant 内外部身份匹配（§26）。POSSIBLE_MATCH 不自动 merge。"""

    EXACT_MATCH = "EXACT_MATCH", _("Exact Match")
    POSSIBLE_MATCH = "POSSIBLE_MATCH", _("Possible Match")
    NO_MATCH = "NO_MATCH", _("No Match")
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", _("Insufficient Data")


class ProfileEthicsStatus(models.TextChoices):
    """HrExternalTeacherProfile.ethics_status（§16/§36 扩展）。"""

    NONE = "NONE", _("None")
    PENDING = "PENDING", _("Pending")
    PASS = "PASS", _("Pass")
    NEEDS_REVIEW = "NEEDS_REVIEW", _("Needs Review")
    FAIL = "FAIL", _("Fail")
    EXPIRED = "EXPIRED", _("Expired")


class IdentityVerificationStatus(models.TextChoices):
    """身份核验状态。"""

    UNVERIFIED = "UNVERIFIED", _("Unverified")
    PENDING = "PENDING", _("Pending")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    EXPIRED = "EXPIRED", _("Expired")


class ExternalTitleAppointmentType(models.TextChoices):
    """称号任命类型（§5.2 Title ≠ Engagement）。"""

    HONORARY_PROFESSOR = "HONORARY_PROFESSOR", _("Honorary Professor")
    GUEST_PROFESSOR = "GUEST_PROFESSOR", _("Guest Professor")
    ADJUNCT_PROFESSOR = "ADJUNCT_PROFESSOR", _("Adjunct Professor")
    INDUSTRY_PROFESSOR = "INDUSTRY_PROFESSOR", _("Industry Professor")
    DISTINGUISHED_EXPERT = "DISTINGUISHED_EXPERT", _("Distinguished Expert")
    SKILL_MASTER = "SKILL_MASTER", _("Skill Master")
    MASTER_CRAFTSPERSON = "MASTER_CRAFTSPERSON", _("Master Craftsperson")
    OTHER = "OTHER", _("Other")


# ---------------------------------------------------------------------------
# Engagement（§19 / §20）
# ---------------------------------------------------------------------------
class ExternalEngagementStatus(models.TextChoices):
    """Engagement 状态机。异常态单独列出。"""

    DRAFT = "DRAFT", _("Draft")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    APPROVED = "APPROVED", _("Approved")
    WAITING_AGREEMENT = "WAITING_AGREEMENT", _("Waiting Agreement")
    SIGNED_WAITING_EFFECTIVE = "SIGNED_WAITING_EFFECTIVE", _("Signed Waiting Effective")
    ACTIVE = "ACTIVE", _("Active")
    REVIEW_DUE = "REVIEW_DUE", _("Review Due")
    RENEWAL_IN_PROGRESS = "RENEWAL_IN_PROGRESS", _("Renewal In Progress")
    EXPIRED = "EXPIRED", _("Expired")
    EXITING = "EXITING", _("Exiting")
    ENDED = "ENDED", _("Ended")
    ARCHIVED = "ARCHIVED", _("Archived")
    # 异常/终局
    RETURNED = "RETURNED", _("Returned")
    REJECTED = "REJECTED", _("Rejected")
    CANCELLED = "CANCELLED", _("Cancelled")
    SUSPENDED = "SUSPENDED", _("Suspended")
    BLOCKED = "BLOCKED", _("Blocked")


class EngagementSourceType(models.TextChoices):
    """Engagement 来源（§9 招聘不是唯一入口）。"""

    COLLEGE_RECOMMENDATION = "COLLEGE_RECOMMENDATION", _("College Recommendation")
    INDUSTRY_POOL = "INDUSTRY_POOL", _("Industry Pool")
    EXPERT_DATABASE = "EXPERT_DATABASE", _("Expert Database")
    SCHOOL_INVITATION = "SCHOOL_INVITATION", _("School Invitation")
    OPEN_SELECTION = "OPEN_SELECTION", _("Open Selection")
    EXTERNAL_RECRUITMENT = "EXTERNAL_RECRUITMENT", _("External Recruitment")
    OTHER = "OTHER", _("Other")


class AgreementRequirement(models.TextChoices):
    """协议要求（§93）。默认正式外聘 REQUIRED_BEFORE_ACTIVATION。"""

    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")
    REQUIRED_BEFORE_ACTIVATION = "REQUIRED_BEFORE_ACTIVATION", _("Required Before Activation")
    REQUIRED_AFTER_ACTIVATION_GRACE = (
        "REQUIRED_AFTER_ACTIVATION_GRACE",
        _("Required After Activation Grace"),
    )


class AgreementProviderStatus(models.TextChoices):
    """HR07 Provider 投影的协议状态（HR07 未交付 → 占位解析）。

    本状态不是 HR08 权威；仅表示从 HR07 侧读取到的协议生命周期结论。
    HR07 交付后由 integrations/hr07.py 映射真实 HrAgreement 状态。
    """

    UNAVAILABLE = "UNAVAILABLE", _("Unavailable")
    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")
    DRAFT = "DRAFT", _("Draft")
    UNDER_APPROVAL = "UNDER_APPROVAL", _("Under Approval")
    WAITING_SIGNATURE = "WAITING_SIGNATURE", _("Waiting Signature")
    SIGNED = "SIGNED", _("Signed")
    ACTIVE = "ACTIVE", _("Active")
    TERMINATED = "TERMINATED", _("Terminated")


class ExternalAssignmentType(models.TextChoices):
    """EngagementAssignment 类型（§22）。"""

    TEACHING = "TEACHING", _("Teaching")
    PRACTICE_GUIDANCE = "PRACTICE_GUIDANCE", _("Practice Guidance")
    INDUSTRY_MENTOR = "INDUSTRY_MENTOR", _("Industry Mentor")
    PROGRAM_DEVELOPMENT = "PROGRAM_DEVELOPMENT", _("Program Development")
    RESEARCH_COLLABORATION = "RESEARCH_COLLABORATION", _("Research Collaboration")
    SKILL_TRAINING = "SKILL_TRAINING", _("Skill Training")
    FACULTY_DEVELOPMENT = "FACULTY_DEVELOPMENT", _("Faculty Development")
    STUDENT_MENTORING = "STUDENT_MENTORING", _("Student Mentoring")
    OTHER = "OTHER", _("Other")


class ExternalAssignmentStatus(models.TextChoices):
    PLANNED = "PLANNED", _("Planned")
    ACTIVE = "ACTIVE", _("Active")
    ENDED = "ENDED", _("Ended")
    CANCELLED = "CANCELLED", _("Cancelled")


# ---------------------------------------------------------------------------
# 聘用审批（§33 / §34）
# ---------------------------------------------------------------------------
class ExternalHiringStatus(models.TextChoices):
    """Hiring Case 状态机。"""

    DRAFT = "DRAFT", _("Draft")
    VALIDATING = "VALIDATING", _("Validating")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_COLLEGE_REVIEW = "UNDER_COLLEGE_REVIEW", _("Under College Review")
    UNDER_HR_REVIEW = "UNDER_HR_REVIEW", _("Under HR Review")
    UNDER_SCHOOL_APPROVAL = "UNDER_SCHOOL_APPROVAL", _("Under School Approval")
    APPROVED = "APPROVED", _("Approved")
    WAITING_AGREEMENT = "WAITING_AGREEMENT", _("Waiting Agreement")
    READY_TO_ACTIVATE = "READY_TO_ACTIVATE", _("Ready To Activate")
    ACTIVATED = "ACTIVATED", _("Activated")
    # 异常/终局
    RETURNED = "RETURNED", _("Returned")
    REJECTED = "REJECTED", _("Rejected")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    CANCELLED = "CANCELLED", _("Cancelled")


class EthicsReviewStatus(models.TextChoices):
    """师德/伦理审查（§36）。系统只提供合规流程，不推断政治倾向/敏感属性。"""

    PENDING = "PENDING", _("Pending")
    PASS = "PASS", _("Pass")
    NEEDS_REVIEW = "NEEDS_REVIEW", _("Needs Review")
    FAIL = "FAIL", _("Fail")
    EXPIRED = "EXPIRED", _("Expired")


class ConflictDeclarationStatus(models.TextChoices):
    """利益冲突声明（§37）。只用于业务合规。"""

    DECLARED = "DECLARED", _("Declared")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    RESOLVED = "RESOLVED", _("Resolved")
    WAIVED = "WAIVED", _("Waived")


class QualificationReviewStatus(models.TextChoices):
    """资格审查（读 HR09 已核验事实；无则 staging evidence 提交核验）。"""

    NOT_APPLICABLE = "NOT_APPLICABLE", _("Not Applicable")
    PENDING = "PENDING", _("Pending")
    PASSED = "PASSED", _("Passed")
    REJECTED = "REJECTED", _("Rejected")
    EXPIRED = "EXPIRED", _("Expired")


# ---------------------------------------------------------------------------
# 任务 / 证据 / 工作量（§46-52）
# ---------------------------------------------------------------------------
class ExternalTaskStatus(models.TextChoices):
    """Service Task 状态（§47）。"""

    DRAFT = "DRAFT", _("Draft")
    ASSIGNED = "ASSIGNED", _("Assigned")
    ACCEPTED = "ACCEPTED", _("Accepted")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    COMPLETED = "COMPLETED", _("Completed")
    REJECTED_FOR_CORRECTION = "REJECTED_FOR_CORRECTION", _("Rejected For Correction")
    CANCELLED = "CANCELLED", _("Cancelled")


class TaskAcceptance(models.TextChoices):
    """任务接受（§56）。拒绝不直接删除任务。"""

    PENDING = "PENDING", _("Pending")
    ACCEPTED = "ACCEPTED", _("Accepted")
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION", _("Request Clarification")
    DECLINED_WITH_REASON = "DECLINED_WITH_REASON", _("Declined With Reason")


class TaskSourceDomain(models.TextChoices):
    """任务来源域（§48）。ACADEMIC 为教务权威，HR08 只存 reference。"""

    ACADEMIC = "ACADEMIC", _("Academic")
    HR08 = "HR08", _("HR08")
    LEGACY_IMPORT = "LEGACY_IMPORT", _("Legacy Import")
    OTHER = "OTHER", _("Other")


class TaskSourceObjectType(models.TextChoices):
    TEACHING_ASSIGNMENT = "TEACHING_ASSIGNMENT", _("Teaching Assignment")
    COURSE_DELIVERY = "COURSE_DELIVERY", _("Course Delivery")
    TEACHING_EVALUATION = "TEACHING_EVALUATION", _("Teaching Evaluation")
    SERVICE_TASK = "SERVICE_TASK", _("Service Task")
    OTHER = "OTHER", _("Other")


class EvidenceStatus(models.TextChoices):
    """任务证据（§50）。"""

    UPLOADED = "UPLOADED", _("Uploaded")
    PENDING_VERIFICATION = "PENDING_VERIFICATION", _("Pending Verification")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")


class WorkloadSource(models.TextChoices):
    """工作量来源（§51）。本人提交不自动成为正式数量（§52）。"""

    ACADEMIC_VERIFIED = "ACADEMIC_VERIFIED", _("Academic Verified")
    SYSTEM_CALCULATED = "SYSTEM_CALCULATED", _("System Calculated")
    MANUAL_WITH_EVIDENCE = "MANUAL_WITH_EVIDENCE", _("Manual With Evidence")
    IMPORT_VERIFIED = "IMPORT_VERIFIED", _("Import Verified")


class WorkloadVerificationStatus(models.TextChoices):
    UNVERIFIED = "UNVERIFIED", _("Unverified")
    PENDING = "PENDING", _("Pending")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")


class SettlementStatus(models.TextChoices):
    """结算依据状态（§53）。HR08 只输出 verified basis，HR15 算金额。"""

    NOT_ELIGIBLE = "NOT_ELIGIBLE", _("Not Eligible")
    PENDING = "PENDING", _("Pending")
    READY = "READY", _("Ready")
    VERIFIED = "VERIFIED", _("Verified")
    LOCKED = "LOCKED", _("Locked")


class ContributionType(models.TextChoices):
    """产业/技能大师专项成果类型（§30）。"""

    COURSE_CO_BUILD = "COURSE_CO_BUILD", _("Course Co-build")
    TRAINING_PROJECT = "TRAINING_PROJECT", _("Training Project")
    PROGRAM_DEVELOPMENT = "PROGRAM_DEVELOPMENT", _("Program Development")
    TALENT_TRAINING_CONSULT = "TALENT_TRAINING_CONSULT", _("Talent Training Consult")
    INDUSTRY_ACADEMIC_COOP = "INDUSTRY_ACADEMIC_COOP", _("Industry-academic Cooperation")
    TECH_ATTACK = "TECH_ATTACK", _("Technical Breakthrough")
    STUDENT_PROJECT_GUIDANCE = "STUDENT_PROJECT_GUIDANCE", _("Student Project Guidance")
    TEACHER_PRACTICE_GUIDANCE = "TEACHER_PRACTICE_GUIDANCE", _("Teacher Practice Guidance")
    SKILL_COMPETITION_GUIDANCE = "SKILL_COMPETITION_GUIDANCE", _("Skill Competition Guidance")
    APPRENTICESHIP_GUIDANCE = "APPRENTICESHIP_GUIDANCE", _("Apprenticeship Guidance")
    FACULTY_TRAINING = "FACULTY_TRAINING", _("Faculty Training")
    INDUSTRY_RESOURCE_IMPORT = "INDUSTRY_RESOURCE_IMPORT", _("Industry Resource Import")
    OTHER = "OTHER", _("Other")


# ---------------------------------------------------------------------------
# 产业教授与技能大师（S4，§27-31）
# ---------------------------------------------------------------------------
class ContributionType(models.TextChoices):
    """产业/技能大师专项成果类型（§30）。"""

    COURSE_CO_BUILD = "COURSE_CO_BUILD", _("Course Co-build")
    TRAINING_PROJECT = "TRAINING_PROJECT", _("Training Project")
    PROGRAM_DEVELOPMENT = "PROGRAM_DEVELOPMENT", _("Program Development")
    TALENT_TRAINING_CONSULT = "TALENT_TRAINING_CONSULT", _("Talent Training Consult")
    INDUSTRY_ACADEMIC_COOP = "INDUSTRY_ACADEMIC_COOP", _("Industry-academic Cooperation")
    TECH_ATTACK = "TECH_ATTACK", _("Technical Breakthrough")
    STUDENT_PROJECT_GUIDANCE = "STUDENT_PROJECT_GUIDANCE", _("Student Project Guidance")
    TEACHER_PRACTICE_GUIDANCE = "TEACHER_PRACTICE_GUIDANCE", _("Teacher Practice Guidance")
    SKILL_COMPETITION_GUIDANCE = "SKILL_COMPETITION_GUIDANCE", _("Skill Competition Guidance")
    APPRENTICESHIP_GUIDANCE = "APPRENTICESHIP_GUIDANCE", _("Apprenticeship Guidance")
    FACULTY_TRAINING = "FACULTY_TRAINING", _("Faculty Training")
    INDUSTRY_RESOURCE_IMPORT = "INDUSTRY_RESOURCE_IMPORT", _("Industry Resource Import")
    OTHER = "OTHER", _("Other")


class ContributionStatus(models.TextChoices):
    """专项成果状态。VERIFIED 为正式结论；不把"提交"当"已核验"（00 §21）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    RETURNED = "RETURNED", _("Returned")


class WorkspaceType(models.TextChoices):
    """技能大师/产业工作空间类型（§31）。"""

    SKILL_MASTER_WORKSHOP = "SKILL_MASTER_WORKSHOP", _("Skill Master Workshop")
    INDUSTRY_TEACHING_WORKSHOP = "INDUSTRY_TEACHING_WORKSHOP", _("Industry Teaching Workshop")
    PRACTICE_BASE = "PRACTICE_BASE", _("Practice Base")
    INDUSTRY_ACADEMIC_PLATFORM = "INDUSTRY_ACADEMIC_PLATFORM", _("Industry-academic Platform")
    OTHER = "OTHER", _("Other")


class WorkspaceStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    ENDED = "ENDED", _("Ended")
    ARCHIVED = "ARCHIVED", _("Archived")


class EvidenceVerificationStatus(models.TextChoices):
    """成果证据核验（§50）。"""

    UPLOADED = "UPLOADED", _("Uploaded")
    PENDING_VERIFICATION = "PENDING_VERIFICATION", _("Pending Verification")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")


# ---------------------------------------------------------------------------
# 续聘 / 退出（§60 / §64 / §65）
# ---------------------------------------------------------------------------
class RenewalDecision(models.TextChoices):
    """续聘决策（§60）。"""

    RENEW = "RENEW", _("Renew")
    RENEW_WITH_CHANGES = "RENEW_WITH_CHANGES", _("Renew With Changes")
    CHANGE_CATEGORY = "CHANGE_CATEGORY", _("Change Category")
    CHANGE_HOST_ORG = "CHANGE_HOST_ORG", _("Change Host Org")
    CONVERT_TO_REGULAR_HR_PROCESS = "CONVERT_TO_REGULAR_HR_PROCESS", _("Convert To Regular HR Process")
    DO_NOT_RENEW = "DO_NOT_RENEW", _("Do Not Renew")
    NEEDS_REVIEW = "NEEDS_REVIEW", _("Needs Review")


class RenewalReviewStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    IN_REVIEW = "IN_REVIEW", _("In Review")
    DECIDED = "DECIDED", _("Decided")
    CANCELLED = "CANCELLED", _("Cancelled")


class ExitStatus(models.TextChoices):
    """Exit Case 状态（§65）。"""

    PLANNED = "PLANNED", _("Planned")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    READY_TO_EXIT = "READY_TO_EXIT", _("Ready To Exit")
    EXITING = "EXITING", _("Exiting")
    ENDED = "ENDED", _("Ended")
    CLEARANCE_PENDING = "CLEARANCE_PENDING", _("Clearance Pending")
    CLOSED = "CLOSED", _("Closed")


class ExitReason(models.TextChoices):
    """退出原因（§64）。具体法律解除归 HR07。"""

    TERM_COMPLETED = "TERM_COMPLETED", _("Term Completed")
    NO_RENEWAL = "NO_RENEWAL", _("No Renewal")
    PERSON_WITHDRAWAL = "PERSON_WITHDRAWAL", _("Person Withdrawal")
    SCHOOL_TERMINATION = "SCHOOL_TERMINATION", _("School Termination")
    TASK_COMPLETED = "TASK_COMPLETED", _("Task Completed")
    ROLE_CONVERTED = "ROLE_CONVERTED", _("Role Converted")
    REGULAR_HIRE = "REGULAR_HIRE", _("Regular Hire")
    COMPLIANCE_REASON = "COMPLIANCE_REASON", _("Compliance Reason")
    OTHER = "OTHER", _("Other")


class PerformanceResult(models.TextChoices):
    """履职评价结果（§71）。"""

    EXCELLENT = "EXCELLENT", _("Excellent")
    GOOD = "GOOD", _("Good")
    QUALIFIED = "QUALIFIED", _("Qualified")
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT", _("Needs Improvement")
    UNQUALIFIED = "UNQUALIFIED", _("Unqualified")


# ---------------------------------------------------------------------------
# 访问授权 / Provisioning（§66-68 / §94-99 / §104）
# ---------------------------------------------------------------------------
class AccessGrantStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    GRANTED = "GRANTED", _("Granted")
    EXPIRED = "EXPIRED", _("Expired")
    REVOKED = "REVOKED", _("Revoked")
    FAILED_RETRYABLE = "FAILED_RETRYABLE", _("Failed Retryable")
    REVOKE_FAILED = "REVOKE_FAILED", _("Revoke Failed")


class ProvisioningOperation(models.TextChoices):
    GRANT = "GRANT", _("Grant")
    REVOKE = "REVOKE", _("Revoke")
    UPDATE = "UPDATE", _("Update")


class ProvisioningStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    SUCCESS = "SUCCESS", _("Success")
    FAILED_RETRYABLE = "FAILED_RETRYABLE", _("Failed Retryable")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")


class AcademicIdentityStatus(models.TextChoices):
    """教务教师身份状态（§96）。"""

    PENDING = "PENDING", _("Pending")
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    EXPIRED = "EXPIRED", _("Expired")
    REVOKED = "REVOKED", _("Revoked")


# ---------------------------------------------------------------------------
# Excel 导入（§110）
# ---------------------------------------------------------------------------
class ExternalImportJobStatus(models.TextChoices):
    UPLOADED = "UPLOADED", _("Uploaded")
    VALIDATING = "VALIDATING", _("Validating")
    VALIDATION_FAILED = "VALIDATION_FAILED", _("Validation Failed")
    READY_TO_COMMIT = "READY_TO_COMMIT", _("Ready To Commit")
    COMMITTING = "COMMITTING", _("Committing")
    COMPLETED = "COMPLETED", _("Completed")
    PARTIAL_FAILED = "PARTIAL_FAILED", _("Partial Failed")
    FAILED = "FAILED", _("Failed")


class ExternalImportJobType(models.TextChoices):
    PROFILE = "PROFILE", _("External Teacher Profile")
    ENGAGEMENT = "ENGAGEMENT", _("Engagement")
    TASK = "TASK", _("Service Task")
    WORKLOAD = "WORKLOAD", _("Workload")


class ExternalImportRowStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    VALID = "VALID", _("Valid")
    INVALID = "INVALID", _("Invalid")
    PREVIEW = "PREVIEW", _("Preview")
    COMMITTED = "COMMITTED", _("Committed")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")


# ---------------------------------------------------------------------------
# 风险（§106-107）
# ---------------------------------------------------------------------------
class RiskSeverity(models.TextChoices):
    INFO = "INFO", _("Info")
    LOW = "LOW", _("Low")
    MEDIUM = "MEDIUM", _("Medium")
    HIGH = "HIGH", _("High")
    CRITICAL = "CRITICAL", _("Critical")


class RiskType(models.TextChoices):
    AGREEMENT_MISSING = "AGREEMENT_MISSING", _("Agreement Missing")
    ENGAGEMENT_EXPIRING = "ENGAGEMENT_EXPIRING", _("Engagement Expiring")
    AGREEMENT_EXPIRING = "AGREEMENT_EXPIRING", _("Agreement Expiring")
    ACCESS_OUTLIVES_ENGAGEMENT = "ACCESS_OUTLIVES_ENGAGEMENT", _("Access Outlives Engagement")
    TASK_OVERDUE = "TASK_OVERDUE", _("Task Overdue")
    WORKLOAD_OVER_CAP = "WORKLOAD_OVER_CAP", _("Workload Over Cap")
    QUALIFICATION_EXPIRED = "QUALIFICATION_EXPIRED", _("Qualification Expired")
    ETHICS_REVIEW_EXPIRED = "ETHICS_REVIEW_EXPIRED", _("Ethics Review Expired")
    UNVERIFIED_WORKLOAD = "UNVERIFIED_WORKLOAD", _("Unverified Workload")
    EXIT_CLEARANCE_PENDING = "EXIT_CLEARANCE_PENDING", _("Exit Clearance Pending")
    ACCESS_REVOCATION_FAILED = "ACCESS_REVOCATION_FAILED", _("Access Revocation Failed")
    ACADEMIC_IDENTITY_DRIFT = "ACADEMIC_IDENTITY_DRIFT", _("Academic Identity Drift")
    LEGACY_PROJECTION_DRIFT = "LEGACY_PROJECTION_DRIFT", _("Legacy Projection Drift")


class ExternalRiskStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    ACKNOWLEDGED = "ACKNOWLEDGED", _("Acknowledged")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    RESOLVED = "RESOLVED", _("Resolved")
    WAIVED = "WAIVED", _("Waived")


# ---------------------------------------------------------------------------
# 通用：数据范围 / 敏感等级 / 权威模式（§89 / 00 §38 / 03 §6）
# ---------------------------------------------------------------------------
class ExternalScopeType(models.TextChoices):
    """HR08 数据范围（§89）。同一 Person 可在多个学院有 Engagement。"""

    SCHOOL = "SCHOOL", _("School")
    COLLEGE = "COLLEGE", _("College")
    ORGANIZATION = "ORGANIZATION", _("Organization")
    ENGAGEMENT = "ENGAGEMENT", _("Engagement")
    ASSIGNED_TASKS = "ASSIGNED_TASKS", _("Assigned Tasks")
    SELF = "SELF", _("Self")


class SensitivityLevel(models.TextChoices):
    PUBLIC_HR = "PUBLIC_HR", _("Public HR")
    RESTRICTED_HR = "RESTRICTED_HR", _("Restricted HR")
    SENSITIVE = "SENSITIVE", _("Sensitive")
    HIGH_SENSITIVE = "HIGH_SENSITIVE", _("High Sensitive")


class ExternalAuthorityMode(models.TextChoices):
    """HR08 权威/legacy 三态（§114）。"""

    LEGACY_EMPLOYEE_TAG_ONLY = "LEGACY_EMPLOYEE_TAG_ONLY", _("Legacy Employee Tag Only")
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
    HR08_AUTHORITY = "HR08_AUTHORITY", _("HR08 Authority")


class ExternalDataBasis(models.TextChoices):
    LEGACY_CURRENT_SNAPSHOT = "LEGACY_CURRENT_SNAPSHOT", _("Legacy Current Snapshot")
    HR08_AUTHORITY = "HR08_AUTHORITY", _("HR08 Authority")
    DUAL_READ_MATCHED = "DUAL_READ_MATCHED", _("Dual Read Matched")
    DUAL_READ_MISMATCH = "DUAL_READ_MISMATCH", _("Dual Read Mismatch")
    UNVERIFIED = "UNVERIFIED", _("Unverified")


# ---------------------------------------------------------------------------
# 错误码（§87 + 扩展）
# ---------------------------------------------------------------------------
HR08_ERROR_CODES = frozenset(
    {
        # 总册 §87
        "EXTERNAL_PERSON_MATCH_REQUIRED",
        "EXTERNAL_DUPLICATE_PROFILE",
        "EXTERNAL_CATEGORY_INVALID",
        "EXTERNAL_ENGAGEMENT_OVERLAP",
        "EXTERNAL_WORKLOAD_OVER_CAP",
        "EXTERNAL_QUALIFICATION_REQUIRED",
        "EXTERNAL_ETHICS_REVIEW_FAILED",
        "EXTERNAL_CONFLICT_REVIEW_REQUIRED",
        "EXTERNAL_AGREEMENT_NOT_READY",
        "EXTERNAL_ACCESS_SCOPE_INVALID",
        "EXTERNAL_ENGAGEMENT_EXPIRED",
        "EXTERNAL_TASK_OUTSIDE_ENGAGEMENT",
        "EXTERNAL_TASK_ALREADY_FINALIZED",
        "EXTERNAL_RENEWAL_ALREADY_EXISTS",
        "EXTERNAL_EXIT_BLOCKED",
        "EXTERNAL_ACCESS_REVOKE_FAILED",
        "VERSION_CONFLICT",
        # A0/安全
        "TENANT_CONTEXT_REQUIRED",
        "CROSS_TENANT_REFERENCE",
        "EXTERNAL_SCOPE_DENIED",
        "SENSITIVE_FIELD_DENIED",
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        # 域内
        "EXTERNAL_PROFILE_NOT_FOUND",
        "EXTERNAL_CATEGORY_CODE_CONFLICT",
        "EXTERNAL_ENGAGEMENT_NOT_FOUND",
        "EXTERNAL_TASK_NOT_FOUND",
        "INVALID_REQUEST",
        "PROVIDER_UNAVAILABLE",
    }
)


# ---------------------------------------------------------------------------
# 权限码（§88）
# ---------------------------------------------------------------------------
HR08_PERMISSIONS = (
    "hr08.profile.view",
    "hr08.profile.create",
    "hr08.profile.sensitive_view",
    "hr08.profile.export",
    "hr08.industry.view",
    "hr08.industry.manage",
    "hr08.hiring.create",
    "hr08.hiring.review",
    "hr08.hiring.approve",
    "hr08.hiring.activate",
    "hr08.task.view",
    "hr08.task.manage",
    "hr08.task.verify",
    "hr08.workload.verify",
    "hr08.renewal.review",
    "hr08.renewal.decide",
    "hr08.exit.manage",
    "hr08.access.view",
    "hr08.access.manage",
)


# ---------------------------------------------------------------------------
# Outbox 事件类型（§103）
# ---------------------------------------------------------------------------
HR08_EVENT_TYPES = frozenset(
    {
        "ExternalHiringCaseSubmitted",
        "ExternalHiringApproved",
        "ExternalEngagementActivated",
        "ExternalAssignmentCreated",
        "ExternalTaskAssigned",
        "ExternalTaskCompleted",
        "ExternalWorkloadVerified",
        "ExternalRenewalDue",
        "ExternalEngagementRenewed",
        "ExternalEngagementEnding",
        "ExternalEngagementEnded",
        "ExternalAccessRevocationRequested",
        "ExternalAccessRevoked",
    }
)
