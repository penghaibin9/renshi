"""
hr_changes/constants.py —— HR06 公共合同常量（S1 冻结）。

对齐总册：
- §7  Change Action 冻结（16 个 V1 规范动作）
- §8  Change Reason
- §10 Case 状态机
- §16 校验等级（BLOCKER/WARNING/INFO）
- §41 权限模型、§42 Data Scope
- §47 错误码、§49 下游 Effects、§59 Outbox 事件

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CaseStatus(models.TextChoices):
    """HrPersonnelChangeCase.status —— 主状态机（总册 §10）。

    主链：DRAFT→VALIDATING→READY_TO_SUBMIT→SUBMITTED→UNDER_APPROVAL
         →RETURNED/RESUBMITTED→APPROVED_WAITING_EFFECTIVE→APPLYING→EFFECTIVE→CLOSED
    终止：REJECTED / WITHDRAWN / CANCELLED / APPLY_FAILED / RESCINDED / CORRECTED
    """

    DRAFT = "DRAFT", _("Draft")
    VALIDATING = "VALIDATING", _("Validating")
    READY_TO_SUBMIT = "READY_TO_SUBMIT", _("Ready to Submit")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_APPROVAL = "UNDER_APPROVAL", _("Under Approval")
    RETURNED = "RETURNED", _("Returned")
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    APPROVED_WAITING_EFFECTIVE = "APPROVED_WAITING_EFFECTIVE", _("Approved Waiting Effective")
    APPLYING = "APPLYING", _("Applying")
    EFFECTIVE = "EFFECTIVE", _("Effective")
    CLOSED = "CLOSED", _("Closed")
    # ---- 终止态 ----
    REJECTED = "REJECTED", _("Rejected")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    CANCELLED = "CANCELLED", _("Cancelled")
    APPLY_FAILED = "APPLY_FAILED", _("Apply Failed")
    RESCINDED = "RESCINDED", _("Rescinded")
    CORRECTED = "CORRECTED", _("Corrected")


# 主链状态（未终局，可继续流转）
CASE_ACTIVE_STATUSES = frozenset(
    {
        CaseStatus.DRAFT,
        CaseStatus.VALIDATING,
        CaseStatus.READY_TO_SUBMIT,
        CaseStatus.SUBMITTED,
        CaseStatus.UNDER_APPROVAL,
        CaseStatus.RETURNED,
        CaseStatus.RESUBMITTED,
        CaseStatus.APPROVED_WAITING_EFFECTIVE,
        CaseStatus.APPLYING,
    }
)
# 终局状态（不再流转）
CASE_TERMINAL_STATUSES = frozenset(
    {
        CaseStatus.EFFECTIVE,
        CaseStatus.CLOSED,
        CaseStatus.REJECTED,
        CaseStatus.WITHDRAWN,
        CaseStatus.CANCELLED,
        CaseStatus.APPLY_FAILED,
        CaseStatus.RESCINDED,
        CaseStatus.CORRECTED,
    }
)


class ChangeActionCode(models.TextChoices):
    """V1 规范动作（总册 §7 冻结，16 个）。"""

    ORG_TRANSFER = "ORG_TRANSFER", _("Org Transfer")
    POSITION_TRANSFER = "POSITION_TRANSFER", _("Position Transfer")
    ORG_POSITION_TRANSFER = "ORG_POSITION_TRANSFER", _("Org and Position Transfer")
    POST_CATEGORY_CHANGE = "POST_CATEGORY_CHANGE", _("Post Category Change")
    EMPLOYEE_CATEGORY_CHANGE = "EMPLOYEE_CATEGORY_CHANGE", _("Employee Category Change")
    EMPLOYMENT_TYPE_CHANGE = "EMPLOYMENT_TYPE_CHANGE", _("Employment Type Change")
    MANAGER_CHANGE = "MANAGER_CHANGE", _("Manager Change")
    LOCATION_CHANGE = "LOCATION_CHANGE", _("Location Change")
    ADD_SECONDARY_ASSIGNMENT = "ADD_SECONDARY_ASSIGNMENT", _("Add Secondary Assignment")
    END_SECONDARY_ASSIGNMENT = "END_SECONDARY_ASSIGNMENT", _("End Secondary Assignment")
    PRIMARY_ASSIGNMENT_SWITCH = "PRIMARY_ASSIGNMENT_SWITCH", _("Primary Assignment Switch")
    TEMPORARY_SECONDMENT = "TEMPORARY_SECONDMENT", _("Temporary Secondment")
    TEMPORARY_ATTACHMENT = "TEMPORARY_ATTACHMENT", _("Temporary Attachment")
    RETURN_FROM_TEMPORARY = "RETURN_FROM_TEMPORARY", _("Return From Temporary")
    BULK_ORG_RESTRUCTURE_MOVE = "BULK_ORG_RESTRUCTURE_MOVE", _("Bulk Org Restructure Move")
    DATA_CORRECTION = "DATA_CORRECTION", _("Data Correction")


# 允许普通用户直接发起的动作（其余走 HR/学院审批链，见 S3 Workflow Resolver）
SELF_SERVICEABLE_ACTIONS = frozenset(
    {
        ChangeActionCode.ORG_TRANSFER,
        ChangeActionCode.POSITION_TRANSFER,
        ChangeActionCode.ORG_POSITION_TRANSFER,
        ChangeActionCode.MANAGER_CHANGE,
        ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
        ChangeActionCode.END_SECONDARY_ASSIGNMENT,
        ChangeActionCode.TEMPORARY_SECONDMENT,
        ChangeActionCode.TEMPORARY_ATTACHMENT,
        ChangeActionCode.RETURN_FROM_TEMPORARY,
    }
)

# 属于"组织重组管理员"动作（最高级批量）
BULK_ONLY_ACTIONS = frozenset({ChangeActionCode.BULK_ORG_RESTRUCTURE_MOVE})

# 数据纠错：更高权限、语义不同于业务异动
CORRECTION_ACTIONS = frozenset({ChangeActionCode.DATA_CORRECTION})


class ImpactLevel(models.TextChoices):
    """校验等级（总册 §16）。"""

    BLOCKER = "BLOCKER", _("Blocker")
    WARNING = "WARNING", _("Warning")
    INFO = "INFO", _("Info")


class ChangePriority(models.TextChoices):
    LOW = "LOW", _("Low")
    NORMAL = "NORMAL", _("Normal")
    HIGH = "HIGH", _("High")
    URGENT = "URGENT", _("Urgent")


class ChangeScopeType(models.TextChoices):
    """Data Scope（总册 §42）。"""

    SCHOOL = "SCHOOL", _("School")
    COLLEGE = "COLLEGE", _("College")
    ORGANIZATION = "ORGANIZATION", _("Organization")
    SELF = "SELF", _("Self")
    ASSIGNED_CASES = "ASSIGNED_CASES", _("Assigned Cases")
    SOURCE_ORG = "SOURCE_ORG", _("Source Org")
    TARGET_ORG = "TARGET_ORG", _("Target Org")


class ProposalValidationStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    VALID = "VALID", _("Valid")
    BLOCKED = "BLOCKED", _("Blocked")
    OVERRIDDEN = "OVERRIDDEN", _("Overridden")


class DownstreamEffectStatus(models.TextChoices):
    """HrChangeDownstreamEffect.status（总册 §49）。"""

    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    SUCCESS = "SUCCESS", _("Success")
    FAILED_RETRYABLE = "FAILED_RETRYABLE", _("Failed Retryable")
    FAILED_TERMINAL = "FAILED_TERMINAL", _("Failed Terminal")
    NOT_REQUIRED = "NOT_REQUIRED", _("Not Required")


class FutureConflictResult(models.TextChoices):
    NO_CONFLICT = "NO_CONFLICT", _("No Conflict")
    REBASE_REQUIRED = "REBASE_REQUIRED", _("Rebase Required")
    HARD_CONFLICT = "HARD_CONFLICT", _("Hard Conflict")


class SourceAssignmentPolicy(models.TextChoices):
    """临时异动原岗策略（总册 §27.4）。"""

    KEEP_ACTIVE = "KEEP_ACTIVE", _("Keep Active")
    SUSPEND = "SUSPEND", _("Suspend")
    REDUCE_FTE = "REDUCE_FTE", _("Reduce FTE")


class ReportingManagerPolicy(models.TextChoices):
    """调动后直属关系策略（总册 §22）。"""

    KEEP = "KEEP", _("Keep")
    DERIVE_FROM_TARGET_ORG = "DERIVE_FROM_TARGET_ORG", _("Derive From Target Org")
    SELECT_EXPLICIT = "SELECT_EXPLICIT", _("Select Explicit")


class EmploymentTypeChangePolicy(models.TextChoices):
    """用工性质变更策略（总册 §25）。"""

    UPDATE_RELATIONSHIP = "UPDATE_RELATIONSHIP", _("Update Relationship")
    CLOSE_AND_CREATE_RELATIONSHIP = "CLOSE_AND_CREATE_RELATIONSHIP", _("Close and Create Relationship")
    REQUIRE_HR07_CONTRACT = "REQUIRE_HR07_CONTRACT", _("Require HR07 Contract")


# ---------------------------------------------------------------------------
# 错误码（总册 §47 冻结）
# ---------------------------------------------------------------------------
HR06_ERROR_CODES = frozenset(
    {
        "TENANT_CONTEXT_REQUIRED",
        "SCOPE_DENIED",
        "CHANGE_INVALID_ACTION",
        "CHANGE_INVALID_REASON",
        "CHANGE_INVALID_STATE",
        "CHANGE_EFFECTIVE_DATE_INVALID",
        "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
        "CHANGE_TARGET_ORG_INVALID",
        "CHANGE_TARGET_POSITION_INVALID",
        "CHANGE_POSITION_CAPACITY_CONFLICT",
        "CHANGE_PRIMARY_ASSIGNMENT_CONFLICT",
        "CHANGE_FUTURE_EVENT_CONFLICT",
        "CHANGE_REBASE_REQUIRED",
        "CHANGE_DEPENDENT_EVENT_EXISTS",
        "CHANGE_TARGET_SCOPE_REQUIRED",
        "CHANGE_APPROVAL_SNAPSHOT_MISMATCH",
        "CHANGE_ALREADY_EFFECTIVE",
        "CHANGE_ALREADY_RESCINDED",
        "CHANGE_CORRECTION_REQUIRES_APPROVAL",
        "VERSION_CONFLICT",
        # ---- 实际抛出补充 ----
        "CHANGE_NOT_FOUND",
        "CHANGE_NOT_SUBMITTED",
        "CHANGE_ALREADY_APPROVED",
        "CHANGE_INVALID_PAYLOAD",
        "CASE_NUMBER_CONFLICT",
        "POSITION_NOT_FOUND",
        "STAFF_NOT_FOUND",
        "ASSIGNMENT_NOT_FOUND",
        "RELATIONSHIP_NOT_FOUND",
        "CHANGE_BULK_PREVALIDATE_FAILED",
        "CHANGE_BULK_PARTIAL_FAILED",
        "CHANGE_DEPENDENCY_BLOCKED",
        "RETURN_TARGET_INVALID",
        "PERMISSION_DENIED",
    }
)


# ---------------------------------------------------------------------------
# 权限码（总册 §41 + 00 §28.2 hr.change 前缀；hr06.* 为 alias 迁移用）
# ---------------------------------------------------------------------------
HR_CHANGE_PERMISSIONS = (
    "hr.change.view",
    "hr.change.create",
    "hr.change.submit",
    "hr.change.approve",
    "hr.change.apply",
    "hr.change.cancel",
    "hr.change.rescind",
    "hr.change.correct",
    "hr.change.override_warning",
    "hr.change.transfer.create",
    "hr.change.identity_change.create",
    "hr.change.temporary.create",
    "hr.change.bulk.create",
    "hr.change.ledger.view",
    "hr.change.ledger.export",
)

# 旧 hr06.* alias → hr.change.*（PermissionAliasMapping 迁移用，不重复授权）
HR06_PERMISSION_ALIASES = {
    "hr06.change.view": "hr.change.view",
    "hr06.change.create": "hr.change.create",
    "hr06.change.submit": "hr.change.submit",
    "hr06.change.approve": "hr.change.approve",
    "hr06.change.apply": "hr.change.apply",
    "hr06.change.cancel": "hr.change.cancel",
    "hr06.change.rescind": "hr.change.rescind",
    "hr06.change.correct": "hr.change.correct",
    "hr06.change.override_warning": "hr.change.override_warning",
    "hr06.transfer.create": "hr.change.transfer.create",
    "hr06.identity_change.create": "hr.change.identity_change.create",
    "hr06.temporary.create": "hr.change.temporary.create",
    "hr06.bulk.create": "hr.change.bulk.create",
    "hr06.ledger.view": "hr.change.ledger.view",
    "hr06.ledger.export": "hr.change.ledger.export",
}


# ---------------------------------------------------------------------------
# Outbox 事件类型（总册 §59 + 00 §28.3 冻结 PersonnelChangeEffective）
# ---------------------------------------------------------------------------
HR06_EVENT_TYPES = frozenset(
    {
        "PersonnelChangeApproved",
        "PersonnelChangeEffective",
        "PersonnelChangeCorrected",
        "PersonnelChangeRescinded",
        "PersonnelChangeSubmitted",
        "PersonnelChangeReturned",
        "PersonnelChangeScheduled",
        "PersonnelChangeApplyFailed",
        "AssignmentChanged",
        "OrganizationTransferred",
        "PositionChanged",
        "StaffCategoryChanged",
        "SecondaryAssignmentAdded",
        "SecondaryAssignmentEnded",
        "TemporaryAssignmentStarted",
        "TemporaryAssignmentEnded",
        "TemporaryAssignmentReturnDue",
        "TemporaryAssignmentOverdue",
        "ContractReviewRequired",
        "CompensationRecalculationRequested",
        "AttendanceRuleReevaluationRequested",
    }
)


# ---------------------------------------------------------------------------
# 受管字段（S9 封堵 & Proposal domain/field_code 约束源；总册 §57）
# ---------------------------------------------------------------------------
# domain → 允许的 field_code 集合
CHANGE_FIELD_CATALOG = {
    "assignment": {
        "organization",
        "position",
        "post_catalog",
        "reporting_staff",
        "fte",
        "assignment_role_code",
        "location",
    },
    "relationship": {"relationship_type", "employment_type", "effective_to"},
    "staff": {"staff_category_code"},
    "temporary": {"expected_return_at", "source_policy", "return_policy"},
}
