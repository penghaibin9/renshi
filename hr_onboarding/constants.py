"""
hr_onboarding/constants.py

HR05 冻结枚举（《05_HR05_入职管理_施工总册_终极版》§5/§7/§8/§12/§14/§15/§17）。

原则：
- Case 状态机是系统权威，学校不允许随便创建（§8 语义冻结）。
- 材料/任务/试用/预占等状态机按总册冻结值，迁移期禁止删除已有值（additive-only）。
- 禁止本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CaseStatus(models.TextChoices):
    """HrOnboardingCase 权威状态机（总册 §8）。

    关键语义（不得合并为一个"完成"）：
    - REPORTED：人确实完成报到动作；
    - ACTIVE：HR03 正式人员事实与核心资格已生效；
    - ONBOARDING_COMPLETED：跨部门入职任务达到完成规则；
    - CONFIRMED：试用转正最终完成。
    """

    # 正常路径
    CREATED = "CREATED", _("Created")
    PREPARING = "PREPARING", _("Preparing")
    READY_TO_REPORT = "READY_TO_REPORT", _("Ready To Report")
    REPORT_SCHEDULED = "REPORT_SCHEDULED", _("Report Scheduled")
    REPORTED = "REPORTED", _("Reported")
    VERIFYING = "VERIFYING", _("Verifying")
    READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION", _("Ready For Activation")
    ACTIVATING = "ACTIVATING", _("Activating")
    ACTIVE = "ACTIVE", _("Active")
    ONBOARDING_IN_PROGRESS = "ONBOARDING_IN_PROGRESS", _("Onboarding In Progress")
    ONBOARDING_COMPLETED = "ONBOARDING_COMPLETED", _("Onboarding Completed")
    PROBATION = "PROBATION", _("Probation")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    # 异常/终止路径
    REPORT_DELAYED = "REPORT_DELAYED", _("Report Delayed")
    DECLINED = "DECLINED", _("Declined")
    NO_SHOW = "NO_SHOW", _("No Show")
    BLOCKED = "BLOCKED", _("Blocked")
    ACTIVATION_FAILED = "ACTIVATION_FAILED", _("Activation Failed")
    CANCELLED = "CANCELLED", _("Cancelled")
    PROBATION_EXTENDED = "PROBATION_EXTENDED", _("Probation Extended")
    PROBATION_FAILED = "PROBATION_FAILED", _("Probation Failed")


class CaseSourceType(models.TextChoices):
    """HrOnboardingCase.source_type —— V1 默认禁止无来源创建（§7）。"""

    HR04_HIRE = "HR04_HIRE", _("HR04 Hire")
    LEGAL_MANUAL_MIGRATION = "LEGAL_MANUAL_MIGRATION", _("Legal Manual Migration")
    TRANSFER_IN = "TRANSFER_IN", _("Transfer In")
    POLICY_IMPORT = "POLICY_IMPORT", _("Policy Import")
    LEGACY_MIGRATION = "LEGACY_MIGRATION", _("Legacy Migration")


class ActivationStatus(models.TextChoices):
    """HrOnboardingCase.activation_status / HrActivationAttempt.status。"""

    NOT_STARTED = "NOT_STARTED", _("Not Started")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    SUCCEEDED = "SUCCEEDED", _("Succeeded")
    PARTIAL_FAILED = "PARTIAL_FAILED", _("Partial Failed")
    FAILED = "FAILED", _("Failed")


class IntentStatus(models.TextChoices):
    """HR05-01 入职意愿（总册 §9.5）。"""

    PENDING = "PENDING", _("Pending")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    REQUESTED_DELAY = "REQUESTED_DELAY", _("Requested Delay")
    DECLINED = "DECLINED", _("Declined")
    NO_RESPONSE = "NO_RESPONSE", _("No Response")


class PersonMatchStatus(models.TextChoices):
    """Activation 前 Person 匹配（总册 §23，tenant-private）。"""

    EXACT_MATCH = "EXACT_MATCH", _("Exact Match")
    POSSIBLE_MATCH = "POSSIBLE_MATCH", _("Possible Match")
    NO_MATCH = "NO_MATCH", _("No Match")
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA", _("Insufficient Data")


class MaterialStatus(models.TextChoices):
    """HrOnboardingMaterial 状态（总册 §12.3）。"""

    MISSING = "MISSING", _("Missing")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    RETURNED = "RETURNED", _("Returned")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    EXPIRED = "EXPIRED", _("Expired")
    WAIVED = "WAIVED", _("Waived")


class MaterialBlockingPhase(models.TextChoices):
    """HrOnboardingMaterialRequirement.blocking_phase（总册 §12.2）。"""

    PRE_REPORT = "PRE_REPORT", _("Before Report")
    REPORT = "REPORT", _("At Report")
    ACTIVATION = "ACTIVATION", _("Before Activation")
    POST_ACTIVATION = "POST_ACTIVATION", _("After Activation")
    PROBATION = "PROBATION", _("Probation")


class MaterialReusePolicy(models.TextChoices):
    """HR04 材料复用策略（总册 §12.6）—— HR05 不无条件继承"已验证"。"""

    TRUST_SOURCE = "TRUST_SOURCE", _("Trust Source")
    REVERIFY = "REVERIFY", _("Re-verify")
    REQUIRE_ORIGINAL = "REQUIRE_ORIGINAL", _("Require Original")


class MaterialSource(models.TextChoices):
    """HrOnboardingMaterial.source。"""

    HR04 = "HR04", _("From HR04")
    PORTAL = "PORTAL", _("Candidate Portal")
    HR_UPLOAD = "HR_UPLOAD", _("HR Upload")
    EXTERNAL_VERIFY = "EXTERNAL_VERIFY", _("External Verify")


class VerificationResult(models.TextChoices):
    """HrMaterialVerification.result（总册 §12.4）。"""

    VERIFIED = "VERIFIED", _("Verified")
    MISMATCH = "MISMATCH", _("Mismatch")
    UNREADABLE = "UNREADABLE", _("Unreadable")
    NEEDS_ORIGINAL = "NEEDS_ORIGINAL", _("Needs Original")
    NEEDS_EXTERNAL_CHECK = "NEEDS_EXTERNAL_CHECK", _("Needs External Check")
    INVALID = "INVALID", _("Invalid")


class TaskStatus(models.TextChoices):
    """HrOnboardingTaskInstance.status —— 权威 9 态（总册 §14.4），保留 UI 5 态语义。"""

    NOT_STARTED = "NOT_STARTED", _("Not Started")
    READY = "READY", _("Ready")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    WAITING_EXTERNAL = "WAITING_EXTERNAL", _("Waiting External")
    BLOCKED = "BLOCKED", _("Blocked")
    COMPLETED = "COMPLETED", _("Completed")
    WAIVED = "WAIVED", _("Waived")
    FAILED = "FAILED", _("Failed")
    CANCELLED = "CANCELLED", _("Cancelled")


class BlockingLevel(models.TextChoices):
    """HrOnboardingTaskDefinition.blocking_level（总册 §14.3）—— 不能只有 is_required。"""

    INFO = "INFO", _("Info")
    NON_BLOCKING = "NON_BLOCKING", _("Non Blocking")
    BLOCKS_ACTIVATION = "BLOCKS_ACTIVATION", _("Blocks Activation")
    BLOCKS_ONBOARDING_COMPLETE = "BLOCKS_ONBOARDING_COMPLETE", _("Blocks Onboarding Complete")
    BLOCKS_PAYROLL = "BLOCKS_PAYROLL", _("Blocks Payroll")
    BLOCKS_WORK_ACCESS = "BLOCKS_WORK_ACCESS", _("Blocks Work Access")


class ResponsibleRole(models.TextChoices):
    """HrOnboardingTaskDefinition.responsible_role —— 不保存具体 Employee ID（§14.6）。"""

    RESPONSIBLE_HR = "RESPONSIBLE_HR", _("Responsible HR")
    COLLEGE_HR = "COLLEGE_HR", _("College HR")
    HIRING_MANAGER = "HIRING_MANAGER", _("Hiring Manager")
    IT_SERVICE = "IT_SERVICE", _("IT Service")
    FINANCE_SERVICE = "FINANCE_SERVICE", _("Finance Service")
    ACADEMIC_SERVICE = "ACADEMIC_SERVICE", _("Academic Service")
    CUSTOM_GROUP = "CUSTOM_GROUP", _("Custom Group")


class TaskCompletionType(models.TextChoices):
    MANUAL = "MANUAL", _("Manual")
    AUTOMATED = "AUTOMATED", _("Automated")


class ProvisioningStatus(models.TextChoices):
    """HrProvisioningRequest.status（总册 §15）。"""

    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    SUCCESS = "SUCCESS", _("Success")
    FAILED_RETRYABLE = "FAILED_RETRYABLE", _("Failed Retryable")
    FAILED_TERMINAL = "FAILED_TERMINAL", _("Failed Terminal")
    CANCELLED = "CANCELLED", _("Cancelled")


class ProbationStatus(models.TextChoices):
    """HrProbationCase.status（总册 §17.2）。"""

    NOT_STARTED = "NOT_STARTED", _("Not Started")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    REVIEW_DUE = "REVIEW_DUE", _("Review Due")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    EXTENDED = "EXTENDED", _("Extended")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    FAILED = "FAILED", _("Failed")
    CANCELLED = "CANCELLED", _("Cancelled")


class ProbationResult(models.TextChoices):
    NONE = "NONE", _("None")
    CONFIRMED = "CONFIRMED", _("Confirmed")
    EXTENDED = "EXTENDED", _("Extended")
    FAILED = "FAILED", _("Failed")


class PortalTokenStatus(models.TextChoices):
    """HrPrehirePortalAccess.status。"""

    ACTIVE = "ACTIVE", _("Active")
    USED = "USED", _("Used")
    EXPIRED = "EXPIRED", _("Expired")
    REVOKED = "REVOKED", _("Revoked")


class PortalTokenPurpose(models.TextChoices):
    PREHIRE_ACCESS = "PREHIRE_ACCESS", _("Prehire Access")
    MATERIAL_UPLOAD = "MATERIAL_UPLOAD", _("Material Upload")
    PROFILE_EDIT = "PROFILE_EDIT", _("Profile Edit")


class RiskCode(models.TextChoices):
    """HR05-01 自动风险（总册 §9.8）。"""

    OFFER_EXPIRING = "OFFER_EXPIRING", _("Offer Expiring")
    REPORT_DATE_NEAR_NO_CONFIRM = "REPORT_DATE_NEAR_NO_CONFIRM", _("Report Date Near No Confirm")
    POSITION_RESERVATION_EXPIRING = "POSITION_RESERVATION_EXPIRING", _("Position Reservation Expiring")
    MISSING_BLOCKING_DOCUMENT = "MISSING_BLOCKING_DOCUMENT", _("Missing Blocking Document")
    PORTAL_NOT_ACTIVATED = "PORTAL_NOT_ACTIVATED", _("Portal Not Activated")
    DELAYED_MULTIPLE_TIMES = "DELAYED_MULTIPLE_TIMES", _("Delayed Multiple Times")


class ReportDelayApprovalStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")


class PersonnelFileStatus(models.TextChoices):
    """HrPersonnelFileTransfer.review_status（总册 §13）。"""

    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")
    TO_BE_REQUESTED = "TO_BE_REQUESTED", _("To Be Requested")
    REQUESTED = "REQUESTED", _("Requested")
    IN_TRANSIT = "IN_TRANSIT", _("In Transit")
    RECEIVED = "RECEIVED", _("Received")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    VERIFIED = "VERIFIED", _("Verified")
    ISSUE_FOUND = "ISSUE_FOUND", _("Issue Found")


class DataConflictStatus(models.TextChoices):
    """HrOnboardingDataConflict.resolution（总册 §22）。"""

    OPEN = "OPEN", _("Open")
    RESOLVED = "RESOLVED", _("Resolved")
    WAIVED = "WAIVED", _("Waived")


class EmploymentType(models.TextChoices):
    """HrOnboardingCase.employment_type —— 与 HR03 EmploymentType 对齐。"""

    FULL_TIME = "FULL_TIME", _("Full Time")
    PART_TIME = "PART_TIME", _("Part Time")
    EXTERNAL = "EXTERNAL", _("External")
    RETIRED_REHIRED = "RETIRED_REHIRED", _("Retired And Rehired")
    OTHER = "OTHER", _("Other")


class StaffCategoryCode(models.TextChoices):
    """HrOnboardingCase.staff_category —— 与 HR03 StaffCategoryCode 对齐。"""

    TEACHER = "TEACHER", _("Teacher")
    ADMIN = "ADMIN", _("Administrative")
    ENGINEERING_TECHNICAL = "ENGINEERING_TECHNICAL", _("Engineering Technical")
    EXPERIMENTAL = "EXPERIMENTAL", _("Experimental")
    LIBRARY_ARCHIVES = "LIBRARY_ARCHIVES", _("Library/Archives")
    LOGISTICS = "LOGISTICS", _("Logistics")
    OTHER = "OTHER", _("Other")


# ---------------------------------------------------------------------------
# 错误码（总册 §35）
# ---------------------------------------------------------------------------
HR05_ERROR_CODES = frozenset(
    {
        "ONBOARDING_CASE_INVALID_SOURCE",
        "ONBOARDING_CASE_DUPLICATE",
        "INVALID_STATE_TRANSITION",
        "POSITION_RESERVATION_INVALID",
        "PERSON_MATCH_REQUIRED",
        "PERSON_MATCH_CONFLICT",
        "BLOCKING_MATERIAL_MISSING",
        "MATERIAL_NOT_VERIFIED",
        "ACTIVATION_ALREADY_COMPLETED",
        "ACTIVATION_PARTIAL_FAILURE",
        "STAFF_NUMBER_CONFLICT",
        "TASK_PREREQUISITE_NOT_MET",
        "TASK_ALREADY_COMPLETED",
        "PORTAL_TOKEN_EXPIRED",
        "PORTAL_TOKEN_REVOKED",
        "PROBATION_ALREADY_FINALIZED",
        "VERSION_CONFLICT",
    }
)


# ---------------------------------------------------------------------------
# Outbox 事件类型（总册 §48）
# ---------------------------------------------------------------------------
HR05_EVENT_TYPES = frozenset(
    {
        "OnboardingCaseCreated",
        "PrehireConfirmed",
        "EmployeeReported",
        "StaffActivated",
        "ProvisioningRequested",
        "ProvisioningSucceeded",
        "ProvisioningFailed",
        "OnboardingCompleted",
        "ProbationReviewDue",
        "ProbationConfirmed",
        "ProbationFailed",
    }
)
