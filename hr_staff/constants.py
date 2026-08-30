"""
hr_staff/constants.py —— HR03 公共合同常量（S1 冻结）。

对齐总册：
- §22 人员状态机（StaffStatus）
- §7.3/7.4 关系与任职类型（RelationshipType/EmploymentType/AssignmentType）
- §6.3 字段权限等级（SensitivityLevel）
- §6.2 数据范围（StaffScopeType）
- §12.4/52.3 事实来源（SourceBusinessType/SourceCategory）
- §27 错误码、§39 权限码
- §30 权威模式（AuthorityMode，与 hr_control_center.providers.base 对齐）
- §15.5 更正影响分级（CorrectionImpactLevel）

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class StaffStatus(models.TextChoices):
    """人员状态 —— 仅为投影，权威由 HrEmploymentRelationship/HrStatusHistory 段推导。"""

    PENDING_ENTRY = "PENDING_ENTRY", _("Pending Entry")
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    DEPARTURE_PENDING = "DEPARTURE_PENDING", _("Departure Pending")
    DEPARTED = "DEPARTED", _("Departed")
    RETIRED = "RETIRED", _("Retired")
    RETIRED_REHIRED = "RETIRED_REHIRED", _("Retired and Rehired")


class RelationshipType(models.TextChoices):
    """HrEmploymentRelationship.relationship_type —— 同一 Person 可多关系。"""

    REGULAR_EMPLOYMENT = "REGULAR_EMPLOYMENT", _("Regular Employment")
    CONTRACT = "CONTRACT", _("Contract")
    LABOR_DISPATCH = "LABOR_DISPATCH", _("Labor Dispatch")
    EXTERNAL_PART_TIME = "EXTERNAL_PART_TIME", _("External Part-time")
    SECONDMENT = "SECONDMENT", _("Secondment")
    RETIRED_REHIRE = "RETIRED_REHIRE", _("Retired Rehire")
    REHIRE = "REHIRE", _("Rehire")
    OTHER = "OTHER", _("Other")


class EmploymentType(models.TextChoices):
    """用工/聘用类型 —— 与人员类别区分，禁止塞进 staff_category 一个下拉。"""

    FULL_TIME = "FULL_TIME", _("Full Time")
    PART_TIME = "PART_TIME", _("Part Time")
    EXTERNAL = "EXTERNAL", _("External")
    RETIRED_REHIRED = "RETIRED_REHIRED", _("Retired and Rehired")
    OTHER = "OTHER", _("Other")


class StaffCategoryCode(models.TextChoices):
    """人员类别（学校可配字典的默认集）。"""

    TEACHER = "TEACHER", _("Teacher")
    ADMIN = "ADMIN", _("Administrative")
    ENGINEERING_TECHNICAL = "ENGINEERING_TECHNICAL", _("Engineering Technical")
    EXPERIMENTAL = "EXPERIMENTAL", _("Experimental")
    LIBRARY_ARCHIVES = "LIBRARY_ARCHIVES", _("Library/Archives")
    LOGISTICS = "LOGISTICS", _("Logistics")
    OTHER = "OTHER", _("Other")


class AssignmentType(models.TextChoices):
    """HrStaffAssignment.assignment_type —— 不能用“单岗位字段+逗号”表达。"""

    PRIMARY = "PRIMARY", _("Primary")
    CONCURRENT = "CONCURRENT", _("Concurrent")
    TEMPORARY = "TEMPORARY", _("Temporary")
    SECONDMENT = "SECONDMENT", _("Secondment")


class AssignmentStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    ACTIVE = "ACTIVE", _("Active")
    ENDING_SOON = "ENDING_SOON", _("Ending Soon")
    ENDED = "ENDED", _("Ended")
    CANCELLED = "CANCELLED", _("Cancelled")


class RelationshipStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    ACTIVE = "ACTIVE", _("Active")
    ENDED = "ENDED", _("Ended")
    CANCELLED = "CANCELLED", _("Cancelled")


class SensitivityLevel(models.TextChoices):
    """字段权限四级（总册 6.3）。"""

    PUBLIC_HR = "PUBLIC_HR", _("Public HR")
    RESTRICTED_HR = "RESTRICTED_HR", _("Restricted HR")
    SENSITIVE = "SENSITIVE", _("Sensitive")
    HIGH_SENSITIVE = "HIGH_SENSITIVE", _("High Sensitive")


class StaffScopeType(models.TextChoices):
    """HR03 数据范围（总册 6.2）—— 先 tenant，再 scope，再 permission，再字段策略。"""

    SCHOOL = "SCHOOL", _("School")
    COLLEGE = "COLLEGE", _("College")
    DEPARTMENT = "DEPARTMENT", _("Department")
    ASSIGNMENT = "ASSIGNMENT", _("Assignment")
    SELF = "SELF", _("Self")
    EXPLICIT_STAFF_SET = "EXPLICIT_STAFF_SET", _("Explicit Staff Set")


class SourceBusinessType(models.TextChoices):
    """正式事实来源（总册 12.4）—— 管理员手工新增必须选择受控来源。"""

    HR05_ONBOARDING = "HR05_ONBOARDING", _("HR05 Onboarding")
    HR06_TRANSFER = "HR06_TRANSFER", _("HR06 Transfer")
    HR06_POSITION_CHANGE = "HR06_POSITION_CHANGE", _("HR06 Position Change")
    HR07_CONTRACT = "HR07_CONTRACT", _("HR07 Contract")
    HR13_TITLE_APPOINTMENT = "HR13_TITLE_APPOINTMENT", _("HR13 Title Appointment")
    HR14_APPOINTMENT = "HR14_APPOINTMENT", _("HR14 Appointment")
    HR16_EXIT = "HR16_EXIT", _("HR16 Exit")
    HR16_REHIRE = "HR16_REHIRE", _("HR16 Rehire")
    MIGRATION_VERIFIED = "MIGRATION_VERIFIED", _("Migration Verified")
    AUTHORIZED_CORRECTION = "AUTHORIZED_CORRECTION", _("Authorized Correction")


class SourceCategory(models.TextChoices):
    """高价值事实可信度来源（总册 52.3）。"""

    SELF_REPORTED = "SELF_REPORTED", _("Self Reported")
    HR_ENTERED = "HR_ENTERED", _("HR Entered")
    MIGRATED = "MIGRATED", _("Migrated")
    VERIFIED_EXTERNAL = "VERIFIED_EXTERNAL", _("Verified External")
    BUSINESS_PROCESS = "BUSINESS_PROCESS", _("Business Process")


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "UNVERIFIED", _("Unverified")
    PENDING = "PENDING", _("Pending")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")
    EXPIRED = "EXPIRED", _("Expired")


class DocumentIdentityType(models.TextChoices):
    """HrPersonIdentityDocument.document_type。"""

    NATIONAL_ID = "NATIONAL_ID", _("National ID")
    PASSPORT = "PASSPORT", _("Passport")
    HK_MACAO_TW = "HK_MACAO_TW", _("HK/Macao/TW Permit")
    FOREIGN_RESIDENT = "FOREIGN_RESIDENT", _("Foreign Resident Permit")
    OTHER = "OTHER", _("Other")


class DuplicateMatchLevel(models.TextChoices):
    HARD_MATCH = "HARD_MATCH", _("Hard Match")
    LIKELY_MATCH = "LIKELY_MATCH", _("Likely Match")
    NO_MATCH = "NO_MATCH", _("No Match")


class AuthorityMode(models.TextChoices):
    """权威/legacy 三态（与 hr_control_center.providers.base 对齐）。"""

    LEGACY_STAFF_ONLY = "LEGACY_STAFF_ONLY", _("Legacy Staff Only")
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
    HR03_AUTHORITY = "HR03_AUTHORITY", _("HR03 Authority")


class DataBasis(models.TextChoices):
    LEGACY_CURRENT_SNAPSHOT = "LEGACY_CURRENT_SNAPSHOT", _("Legacy Current Snapshot")
    HR03_AUTHORITY = "HR03_AUTHORITY", _("HR03 Authority")
    DUAL_READ_MATCHED = "DUAL_READ_MATCHED", _("Dual Read Matched")
    DUAL_READ_MISMATCH = "DUAL_READ_MISMATCH", _("Dual Read Mismatch")
    UNVERIFIED = "UNVERIFIED", _("Unverified")


class CorrectionEditMode(models.TextChoices):
    """HrFieldGovernancePolicy.edit_mode（总册 15.2）。"""

    SELF_DIRECT = "SELF_DIRECT", _("Self Direct")
    SELF_REQUEST = "SELF_REQUEST", _("Self Request")
    HR_DIRECT = "HR_DIRECT", _("HR Direct")
    HR_APPROVAL = "HR_APPROVAL", _("HR Approval")
    BUSINESS_PROCESS_ONLY = "BUSINESS_PROCESS_ONLY", _("Business Process Only")
    LOCKED = "LOCKED", _("Locked")


class CorrectionImpactLevel(models.TextChoices):
    """更正影响分析（总册 15.5）。"""

    NO_DOWNSTREAM_IMPACT = "NO_DOWNSTREAM_IMPACT", _("No Downstream Impact")
    REQUIRES_REINDEX = "REQUIRES_REINDEX", _("Requires Reindex")
    REQUIRES_DASHBOARD_RECALC = "REQUIRES_DASHBOARD_RECALC", _("Requires Dashboard Recalc")
    AFFECTS_CLOSED_PAYROLL = "AFFECTS_CLOSED_PAYROLL", _("Affects Closed Payroll")
    AFFECTS_ARCHIVED_ASSESSMENT = "AFFECTS_ARCHIVED_ASSESSMENT", _("Affects Archived Assessment")
    AFFECTS_REPORTED_DATA = "AFFECTS_REPORTED_DATA", _("Affects Reported Data")
    HIGH_RISK_RETROACTIVE = "HIGH_RISK_RETROACTIVE", _("High Risk Retroactive")


class CorrectionStatus(models.TextChoices):
    """更正状态机（总册 15.3）。"""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    RETURNED = "RETURNED", _("Returned")
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    APPROVED = "APPROVED", _("Approved")
    APPLYING = "APPLYING", _("Applying")
    APPLIED = "APPLIED", _("Applied")
    FAILED = "FAILED", _("Failed")
    REJECTED = "REJECTED", _("Rejected")
    CANCELLED = "CANCELLED", _("Cancelled")


class MaterialCategoryCode(models.TextChoices):
    """人事材料分类字典（总册 14.2）。"""

    IDENTITY = "IDENTITY", _("Identity")
    EDUCATION = "EDUCATION", _("Education")
    DEGREE = "DEGREE", _("Degree")
    TEACHER_QUALIFICATION = "TEACHER_QUALIFICATION", _("Teacher Qualification")
    PROFESSIONAL_CERTIFICATE = "PROFESSIONAL_CERTIFICATE", _("Professional Certificate")
    SKILL_CERTIFICATE = "SKILL_CERTIFICATE", _("Skill Certificate")
    EMPLOYMENT = "EMPLOYMENT", _("Employment")
    APPOINTMENT = "APPOINTMENT", _("Appointment")
    CONTRACT_REFERENCE = "CONTRACT_REFERENCE", _("Contract Reference")
    HONOR = "HONOR", _("Honor")
    CORRECTION_EVIDENCE = "CORRECTION_EVIDENCE", _("Correction Evidence")
    OTHER_HR = "OTHER_HR", _("Other HR")


class MaterialVersionStatus(models.TextChoices):
    CURRENT = "CURRENT", _("Current")
    REPLACED = "REPLACED", _("Replaced")
    VOID = "VOID", _("Void")
    RETIRED = "RETIRED", _("Retired")


class ImportJobStatus(models.TextChoices):
    UPLOADED = "UPLOADED", _("Uploaded")
    VALIDATING = "VALIDATING", _("Validating")
    VALIDATION_FAILED = "VALIDATION_FAILED", _("Validation Failed")
    READY_TO_COMMIT = "READY_TO_COMMIT", _("Ready to Commit")
    COMMITTING = "COMMITTING", _("Committing")
    COMPLETED = "COMPLETED", _("Completed")
    PARTIAL_FAILED = "PARTIAL_FAILED", _("Partial Failed")
    FAILED = "FAILED", _("Failed")


# ---------------------------------------------------------------------------
# 错误码（总册 §27）
# ---------------------------------------------------------------------------
HR03_ERROR_CODES = frozenset(
    {
        "STAFF_NOT_FOUND",
        "STAFF_SCOPE_DENIED",
        "SENSITIVE_FIELD_DENIED",
        "TENANT_CONTEXT_REQUIRED",
        "CROSS_TENANT_REFERENCE",
        "PERSON_DUPLICATE_HARD_MATCH",
        "PERSON_DUPLICATE_REVIEW_REQUIRED",
        "STAFF_NO_CONFLICT",
        "ASSIGNMENT_OVERLAP",
        "PRIMARY_ASSIGNMENT_CONFLICT",
        "POSITION_CAPACITY_EXCEEDED",
        "EFFECTIVE_DATE_INVALID",
        "RETROACTIVE_CHANGE_REQUIRES_APPROVAL",
        "CORRECTION_POLICY_DENIED",
        "MATERIAL_ACCESS_DENIED",
        "MATERIAL_VERSION_CONFLICT",
        "VERSION_CONFLICT",
        "LEGACY_AUTHORITY_MISMATCH",
        "AUTHORITY_UNAVAILABLE",
        # ---- 实际抛出补充（P2-9 对齐）----
        "ORG_MAPPING_MISSING",
        "FTE_POLICY_EXCEEDED",
        "INVALID_FTE",
        "ASSIGNMENT_NOT_FOUND",
        "RELATIONSHIP_NOT_FOUND",
        "CORRECTION_STATE_INVALID",
        "CORRECTION_NOT_FOUND",
        "MATERIAL_NOT_FOUND",
        "MATERIAL_VERSION_NOT_FOUND",
        "MATERIAL_TICKET_INVALID",
        "MATERIAL_TICKET_EXPIRED",
        "MATERIAL_TICKET_USED_UP",
        "PURPOSE_REQUIRED",
        "DUPLICATE_STAFF_MASTER",
        "SENSITIVE_FIELD_NOT_FOUND",
        "EVENT_CONSUMPTION_FAILED",
        "CORRECTION_APPLY_FAILED",
    }
)


# ---------------------------------------------------------------------------
# 权限码（总册 §39）
# ---------------------------------------------------------------------------
HR_STAFF_PERMISSIONS = (
    "hr.staff.view",
    "hr.staff.view_sensitive",
    "hr.staff.reveal_high_sensitive",
    "hr.staff.create",
    "hr.staff.edit_basic",
    "hr.staff.export",
    "hr.staff.export_sensitive",
    "hr.staff.import",
    "hr.staff.assignment.view",
    "hr.staff.assignment.correct",
    "hr.staff.background.view",
    "hr.staff.background.manage",
    "hr.staff.material.view",
    "hr.staff.material.upload",
    "hr.staff.material.verify",
    "hr.staff.material.download_sensitive",
    "hr.staff.correction.view",
    "hr.staff.correction.create",
    "hr.staff.correction.review",
    "hr.staff.correction.approve_high_risk",
    "hr.staff.audit.view",
    "hr.staff.data_quality.manage",
    "hr.staff.personnel_decision.view",
    "hr.staff.personnel_decision.manage",
    "hr.staff.reward_disciplinary.view",
    "hr.staff.reward_disciplinary.manage",
)


# ---------------------------------------------------------------------------
# Outbox 事件类型（总册 §30）
# ---------------------------------------------------------------------------
HR03_EVENT_TYPES = frozenset(
    {
        "hr.staff.staff.created",
        "hr.staff.staff.activated",
        "hr.staff.staff.status_changed",
        "hr.staff.employment_relationship.started",
        "hr.staff.employment_relationship.ended",
        "hr.staff.assignment.primary_changed",
        "hr.staff.assignment.concurrent_changed",
        "hr.staff.staff.basic_info_corrected",
        "hr.staff.credential.changed",
        "hr.staff.material.verified",
        "hr.staff.authority_mode.changed",
        "hr.staff.personnel_decision.effective",
        "hr.staff.reward_disciplinary.effective",
    }
)
