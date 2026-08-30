"""
hr_qualification/constants.py —— HR09 公共合同常量（S1 冻结）。

对齐总册《09_HR09_教师资格与双师型_施工总册_终极版》：
- §18 CredentialCategory（资格目录分类）
- §19 QualificationType（教师资格子类）
- §21 CredentialStatus（证书状态机）
- §22 VerificationResult（核验结果）
- §23 VerificationType（核验类型）
- §27 DocumentType（证书文档类型）
- §30 RequirementCompareResult（需求匹配结果）
- §35 JurisdictionLevel（规则层级）
- §38 RuleType（规则类型）
- §40 EvidenceSource（证据来源）
- §53 BatchStatus（批次状态）
- §55 ApplicationStatus（申报状态）
- §72 ConflictStatus（利益冲突）
- §74 ReviewMethod（评审方式）
- §78 Vote（投票）
- §85 RecognitionStatus（认定状态）
- §87 RecheckTrigger（复核触发）
- §88 RecheckDecision（复核决策）
- §91 RiskType（风险类型）
- §106 Permission Codes
- §112 Error Codes
- §119 Outbox Events

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# ============================================================================
# Credential Catalog & Credential Level
# ============================================================================

class CredentialCategory(models.TextChoices):
    """资格目录一级分类（总册 §18）。"""
    TEACHER_QUALIFICATION = "TEACHER_QUALIFICATION", _("Teacher Qualification")
    VOCATIONAL_QUALIFICATION = "VOCATIONAL_QUALIFICATION", _("Vocational Qualification")
    VOCATIONAL_SKILL_LEVEL = "VOCATIONAL_SKILL_LEVEL", _("Vocational Skill Level")
    NON_TEACHER_PROFESSIONAL_TITLE = "NON_TEACHER_PROFESSIONAL_TITLE", _("Non-Teacher Professional Title")
    PROFESSIONAL_LICENSE = "PROFESSIONAL_LICENSE", _("Professional License")
    INDUSTRY_CERTIFICATION = "INDUSTRY_CERTIFICATION", _("Industry Certification")
    TRAINING_CERTIFICATE = "TRAINING_CERTIFICATE", _("Training Certificate")
    OTHER = "OTHER", _("Other")


class TeacherQualificationType(models.TextChoices):
    """教师资格子类（总册 §19）。"""
    HIGHER_EDUCATION_TEACHER = "HIGHER_EDUCATION_TEACHER", _("Higher Education Teacher")
    SECONDARY_VOCATIONAL_TEACHER = "SECONDARY_VOCATIONAL_TEACHER", _("Secondary Vocational Teacher")
    SECONDARY_VOCATIONAL_PRACTICE_INSTRUCTOR = "SECONDARY_VOCATIONAL_PRACTICE_INSTRUCTOR", _("Secondary Vocational Practice Instructor")
    OTHER_LEGAL_TEACHER_QUALIFICATION = "OTHER_LEGAL_TEACHER_QUALIFICATION", _("Other Legal Teacher Qualification")


class IssuerType(models.TextChoices):
    """签发机构类型。"""
    EDUCATION_AUTHORITY = "EDUCATION_AUTHORITY", _("Education Authority")
    MOHRSS = "MOHRSS", _("MOHRSS")  # 人力资源和社会保障部门
    ASSESSMENT_AGENCY = "ASSESSMENT_AGENCY", _("Assessment Agency")
    TITLE_APPROVAL_AUTHORITY = "TITLE_APPROVAL_AUTHORITY", _("Title Approval Authority")
    INDUSTRY_ORG = "INDUSTRY_ORG", _("Industry Organization")
    TRAINING_INSTITUTION = "TRAINING_INSTITUTION", _("Training Institution")
    OTHER_ISSUER = "OTHER_ISSUER", _("Other")


# ============================================================================
# Credential Status（证书状态机 · 总册 §21）
# ============================================================================

class CredentialStatus(models.TextChoices):
    """证书主状态（不可逆的主业务状态）。"""
    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    UNDER_VERIFICATION = "UNDER_VERIFICATION", _("Under Verification")
    ACTIVE = "ACTIVE", _("Active")
    EXPIRED = "EXPIRED", _("Expired")
    SUSPENDED = "SUSPENDED", _("Suspended")
    REVOKED = "REVOKED", _("Revoked")
    INVALID = "INVALID", _("Invalid")
    SUPERSEDED = "SUPERSEDED", _("Superseded")
    ARCHIVED = "ARCHIVED", _("Archived")


# ============================================================================
# Verification（核验 · 总册 §22-24）
# ============================================================================

class VerificationType(models.TextChoices):
    """核验类型（总册 §23）。"""
    MANUAL_ORIGINAL_REVIEW = "MANUAL_ORIGINAL_REVIEW", _("Manual Original Review")
    OFFICIAL_DATABASE = "OFFICIAL_DATABASE", _("Official Database")
    THIRD_PARTY_PROVIDER = "THIRD_PARTY_PROVIDER", _("Third Party Provider")
    ISSUER_CONFIRMATION = "ISSUER_CONFIRMATION", _("Issuer Confirmation")
    IMPORT_TRUSTED_SOURCE = "IMPORT_TRUSTED_SOURCE", _("Import Trusted Source")
    MIGRATION_VERIFIED = "MIGRATION_VERIFIED", _("Migration Verified")


class VerificationResult(models.TextChoices):
    """核验结果（总册 §22）。"""
    PENDING = "PENDING", _("Pending")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    VERIFIED = "VERIFIED", _("Verified")
    NOT_FOUND = "NOT_FOUND", _("Not Found")
    MISMATCH = "MISMATCH", _("Mismatch")
    EXPIRED = "EXPIRED", _("Expired")
    REVOKED = "REVOKED", _("Revoked")
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW", _("Needs Manual Review")
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", _("Provider Unavailable")


# ============================================================================
# Credential Document（总册 §26）
# ============================================================================

class CredentialDocumentType(models.TextChoices):
    """证书相关文档类型。"""
    CERTIFICATE_SCAN = "CERTIFICATE_SCAN", _("Certificate Scan")
    OFFICIAL_VERIFICATION = "OFFICIAL_VERIFICATION", _("Official Verification Document")
    RENEWAL_DOCUMENT = "RENEWAL_DOCUMENT", _("Renewal Document")
    REVOCATION_NOTICE = "REVOCATION_NOTICE", _("Revocation Notice")
    OTHER_DOC = "OTHER_DOC", _("Other")


# ============================================================================
# Credential Requirement（总册 §29-30）
# ============================================================================

class RequirementTargetType(models.TextChoices):
    """需求目标类型。"""
    HR02_POST = "HR02_POST", _("HR02 Post")
    HR08_EXTERNAL_CATEGORY = "HR08_EXTERNAL_CATEGORY", _("HR08 External Category")
    HR09_DOUBLE_TEACHER_LEVEL = "HR09_DOUBLE_TEACHER_LEVEL", _("HR09 Double Teacher Level")
    OTHER_TARGET = "OTHER_TARGET", _("Other")


class RequirementMatchResult(models.TextChoices):
    """Person vs Requirement 比较结果（总册 §30）。"""
    MET = "MET", _("Met")
    MISSING = "MISSING", _("Missing")
    EXPIRED = "EXPIRED", _("Expired")
    UNVERIFIED = "UNVERIFIED", _("Unverified")
    LOWER_LEVEL = "LOWER_LEVEL", _("Lower Level")
    EQUIVALENT_ROUTE_AVAILABLE = "EQUIVALENT_ROUTE_AVAILABLE", _("Equivalent Route Available")
    NOT_APPLICABLE = "NOT_APPLICABLE", _("Not Applicable")


class HardOrSoft(models.TextChoices):
    HARD = "HARD", _("Hard Requirement")
    SOFT = "SOFT", _("Soft / Preferred")


# ============================================================================
# Double Teacher Rule Pack（双师规则 · 总册 §35-37）
# ============================================================================

class JurisdictionLevel(models.TextChoices):
    """规则管辖层级（总册 §35）。"""
    NATIONAL_BASELINE = "NATIONAL_BASELINE", _("National Baseline")
    PROVINCIAL = "PROVINCIAL", _("Provincial")
    SCHOOL = "SCHOOL", _("School")
    BATCH_OVERRIDE = "BATCH_OVERRIDE", _("Batch Override")


class RulePackVersionStatus(models.TextChoices):
    """规则版本状态（总册 §48）。"""
    DRAFT = "DRAFT", _("Draft")
    VALIDATING = "VALIDATING", _("Validating")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    APPROVED = "APPROVED", _("Approved")
    ACTIVE = "ACTIVE", _("Active")           # IMMUTABLE 后
    RETIRED = "RETIRED", _("Retired")


class RuleType(models.TextChoices):
    """规则类型（总册 §38）。"""
    BOOLEAN_FACT = "BOOLEAN_FACT", _("Boolean Fact")
    COUNT = "COUNT", _("Count")
    DURATION = "DURATION", _("Duration")
    LEVEL_AT_LEAST = "LEVEL_AT_LEAST", _("Level At Least")
    ONE_OF = "ONE_OF", _("One Of")
    ALL_OF = "ALL_OF", _("All Of")
    ANY_OF = "ANY_OF", _("Any Of")
    DATE_VALID = "DATE_VALID", _("Date Valid")
    ROLE_REQUIRED = "ROLE_REQUIRED", _("Role Required")
    AWARD_LEVEL = "AWARD_LEVEL", _("Award Level")
    PROJECT_ROLE = "PROJECT_ROLE", _("Project Role")
    EQUIVALENCY = "EQUIVALENCY", _("Equivalency")
    MANUAL_COMMITTEE = "MANUAL_COMMITTEE", _("Manual Committee")


class RecognitionLevel(models.TextChoices):
    """双师型认定层级（总册 §6）。"""
    DOUBLE_TEACHER_JUNIOR = "DOUBLE_TEACHER_JUNIOR", _("Junior")
    DOUBLE_TEACHER_INTERMEDIATE = "DOUBLE_TEACHER_INTERMEDIATE", _("Intermediate")
    DOUBLE_TEACHER_SENIOR = "DOUBLE_TEACHER_SENIOR", _("Senior")


# 国家标准核心维度编码（总册 §5）
class DoubleTeacherDimension(models.TextChoices):
    ETHICS_AND_CONDUCT = "ETHICS_AND_CONDUCT", _("Ethics and Conduct")
    TEACHING_ABILITY = "TEACHING_ABILITY", _("Teaching Ability")
    PRACTICAL_TEACHING = "PRACTICAL_TEACHING", _("Practical Teaching")
    TEACHING_RESEARCH = "TEACHING_RESEARCH", _("Teaching Research")
    PROGRAM_DEVELOPMENT = "PROGRAM_DEVELOPMENT", _("Program Development")
    ENTERPRISE_EXPERIENCE = "ENTERPRISE_EXPERIENCE", _("Enterprise Experience")
    INDUSTRY_PRACTICE = "INDUSTRY_PRACTICE", _("Industry Practice")
    PROFESSIONAL_SKILL = "PROFESSIONAL_SKILL", _("Professional Skill")
    VOCATIONAL_CERTIFICATE = "VOCATIONAL_CERTIFICATE", _("Vocational Certificate")
    NON_TEACHER_PROFESSIONAL_TITLE = "NON_TEACHER_PROFESSIONAL_TITLE", _("Non-Teacher Professional Title")
    TECHNICAL_INNOVATION = "TECHNICAL_INNOVATION", _("Technical Innovation")
    RESULT_TRANSFORMATION = "RESULT_TRANSFORMATION", _("Result Transformation")
    TEACHING_AWARD = "TEACHING_AWARD", _("Teaching Award")
    SKILL_COMPETITION = "SKILL_COMPETITION", _("Skill Competition")
    STUDENT_COMPETITION_GUIDANCE = "STUDENT_COMPETITION_GUIDANCE", _("Student Competition Guidance")
    TEAM_LEADERSHIP = "TEAM_LEADERSHIP", _("Team Leadership")
    TEACHER_DEVELOPMENT_CONTRIBUTION = "TEACHER_DEVELOPMENT_CONTRIBUTION", _("Teacher Development Contribution")
    INDUSTRY_IMPACT = "INDUSTRY_IMPACT", _("Industry Impact")
    OTHER_EQUIVALENT_CAPABILITY = "OTHER_EQUIVALENT_CAPABILITY", _("Other Equivalent Capability")
    # 复合维度（跨多个单维度组合）
    PROFESSIONAL_KNOWLEDGE = "PROFESSIONAL_KNOWLEDGE", _("Professional Knowledge")
    VOCATIONAL_CERTIFICATE_OR_EQUIV = "VOCATIONAL_CERTIFICATE_OR_EQUIV", _("Vocational Certificate or Equivalent")
    INTERMEDIATE_SKILL_OR_EQUIV = "INTERMEDIATE_SKILL_OR_EQUIV", _("Intermediate Skill or Equivalent")
    SENIOR_SKILL_OR_EQUIV = "SENIOR_SKILL_OR_EQUIV", _("Senior Skill or Equivalent")


# ============================================================================
# Evidence（证据 · 总册 §40/§60）
# ============================================================================

class EvidenceCategory(models.TextChoices):
    """证据分类。"""
    SYSTEM_EVIDENCE = "SYSTEM_EVIDENCE", _("System Evidence")
    MANUAL_SUBMITTED = "MANUAL_SUBMITTED", _("Manual Submitted")


class EvidenceVerificationStatus(models.TextChoices):
    """人工提交证据验证状态（总册 §60）。"""
    UNVERIFIED = "UNVERIFIED", _("Unverified")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    VERIFIED = "VERIFIED", _("Verified")
    REJECTED = "REJECTED", _("Rejected")


class EvidenceSourceDomain(models.TextChoices):
    """证据来源域（总册 §40）。"""
    HR03_EDUCATION = "HR03_EDUCATION", _("HR03 Education")
    HR03_WORK_HISTORY = "HR03_WORK_HISTORY", _("HR03 Work History")
    HR09_CREDENTIAL = "HR09_CREDENTIAL", _("HR09 Credential")
    HR10_ENTERPRISE_PRACTICE = "HR10_ENTERPRISE_PRACTICE", _("HR10 Enterprise Practice")
    HR10_TRAINING = "HR10_TRAINING", _("HR10 Training")
    ACADEMIC_TEACHING = "ACADEMIC_TEACHING", _("Academic Teaching")
    ACADEMIC_COURSE_DEVELOPMENT = "ACADEMIC_COURSE_DEVELOPMENT", _("Academic Course Development")
    ACADEMIC_COMPETITION = "ACADEMIC_COMPETITION", _("Academic Competition")
    HR12_ASSESSMENT = "HR12_ASSESSMENT", _("HR12 Assessment")
    RESEARCH_PROJECT = "RESEARCH_PROJECT", _("Research Project")
    MANUAL_VERIFIED = "MANUAL_VERIFIED", _("Manual Verified")


# ============================================================================
# Provider Status（统一 · 总册 §11/§40）
# ============================================================================

class ProviderStatus(models.TextChoices):
    OK = "OK", _("OK")
    PARTIAL = "PARTIAL", _("Partial")
    UNAVAILABLE = "UNAVAILABLE", _("Unavailable")          # ≠ 0 ≠ false ≠ empty
    STALE = "STALE", _("Stale")
    ERROR = "ERROR", _("Error")
    NOT_APPLICABLE = "NOT_APPLICABLE", _("Not Applicable")


# ============================================================================
# Recognition Batch（认定批次 · 总册 §52-53）
# ============================================================================

class BatchStatus(models.TextChoices):
    """认定批次状态（总册 §53）。"""
    DRAFT = "DRAFT", _("Draft")
    PUBLISHED = "PUBLISHED", _("Published")
    APPLICATION_OPEN = "APPLICATION_OPEN", _("Application Open")
    APPLICATION_CLOSED = "APPLICATION_CLOSED", _("Application Closed")
    REVIEWING = "REVIEWING", _("Reviewing")
    RESULT_PENDING = "RESULT_PENDING", _("Result Pending")
    RESULT_PUBLISHED = "RESULT_PUBLISHED", _("Result Published")
    CLOSED = "CLOSED", _("Closed")
    ARCHIVED = "ARCHIVED", _("Archived")


class EligibleScope(models.TextChoices):
    """批次 eligible scope（总册 §52）。"""
    PROFESSIONAL_COURSE_TEACHER = "PROFESSIONAL_COURSE_TEACHER", _("Professional Course Teacher")
    PRACTICE_INSTRUCTOR = "PRACTICE_INSTRUCTOR", _("Practice Instructor")
    ELIGIBLE_EXTERNAL_TEACHER = "ELIGIBLE_EXTERNAL_TEACHER", _("Eligible External Teacher")
    OTHER_ELIGIBLE = "OTHER_ELIGIBLE", _("Other Eligible")


# ============================================================================
# Application（申报 · 总册 §54-55）
# ============================================================================

class ApplicationStatus(models.TextChoices):
    """申报状态机（总册 §55）。"""
    DRAFT = "DRAFT", _("Draft")
    PRECHECKING = "PRECHECKING", _("Prechecking")
    READY = "READY", _("Ready")
    SUBMITTED = "SUBMITTED", _("Submitted")
    FORMAL_REVIEW = "FORMAL_REVIEW", _("Formal Review")
    RETURNED = "RETURNED", _("Returned")                 # 可补正
    RESUBMITTED = "RESUBMITTED", _("Resubmitted")
    ELIGIBLE = "ELIGIBLE", _("Eligible")
    PANEL_REVIEW = "PANEL_REVIEW", _("Panel Review")
    RESULT_PENDING = "RESULT_PENDING", _("Result Pending")
    RECOGNIZED = "RECOGNIZED", _("Recognized")
    NOT_RECOGNIZED = "NOT_RECOGNIZED", _("Not Recognized")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    CANCELLED = "CANCELLED", _("Cancelled")
    OBJECTION = "OBJECTION", _("Objection")


class ApplicationRoute(models.TextChoices):
    NORMAL = "NORMAL", _("Normal")
    EXCEPTION = "EXCEPTION", _("Exception / Breakthrough")


# ============================================================================
# Precheck（系统预检 · 总册 §61）
# ============================================================================

class PrecheckResultType(models.TextChoices):
    """预检结果（总册 §61）。"""
    PASS = "PASS", _("Pass")
    FAIL_HARD_RULE = "FAIL_HARD_RULE", _("Fail Hard Rule")
    MISSING_EVIDENCE = "MISSING_EVIDENCE", _("Missing Evidence")
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED", _("Manual Review Required")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("Source Unavailable")
    RULE_ERROR = "RULE_ERROR", _("Rule Error")


# ============================================================================
# Review（评审 · 总册 §70-82）
# ============================================================================

class ConflictStatus(models.TextChoices):
    """利益冲突状态（总册 §72）。"""
    CLEAR = "CLEAR", _("Clear")
    DECLARED = "DECLARED", _("Declared")
    DETECTED = "DETECTED", _("Detected")
    RECUSED = "RECUSED", _("Recused")
    OVERRIDDEN = "OVERRIDDEN", _("Overridden")


class ReviewMethod(models.TextChoices):
    """评审方式（总册 §74）。"""
    RULE_CONFIRMATION = "RULE_CONFIRMATION", _("Rule Confirmation")
    RUBRIC_SCORING = "RUBRIC_SCORING", _("Rubric Scoring")
    VOTE = "VOTE", _("Vote")
    COMBINED = "COMBINED", _("Combined")


class ScoreSheetStatus(models.TextChoices):
    """评分表状态（总册 §76-77）。"""
    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    LOCKED = "LOCKED", _("Locked")
    VOID = "VOID", _("Void")


class PanelMemberRole(models.TextChoices):
    """Panel 成员角色（总册 §71）。"""
    CHAIR = "CHAIR", _("Chair")
    MEMBER = "MEMBER", _("Member")
    SECRETARY = "SECRETARY", _("Secretary")
    OBSERVER = "OBSERVER", _("Observer")


class VoteChoice(models.TextChoices):
    """投票选项（总册 §78）。"""
    APPROVE = "APPROVE", _("Approve")
    NOT_APPROVE = "NOT_APPROVE", _("Not Approve")
    ABSTAIN = "ABSTAIN", _("Abstain")
    RECUSED = "RECUSED", _("Recused")


class FormalReviewDecision(models.TextChoices):
    """形式审查结论（总册 §69）。"""
    RETURN = "RETURN", _("Return")
    ELIGIBLE = "ELIGIBLE", _("Eligible")
    INELIGIBLE = "INELIGIBLE", _("Ineligible")
    NEEDS_ESCALATION = "NEEDS_ESCALATION", _("Needs Escalation")


# ============================================================================
# Recognition（认定结果 · 总册 §84-85）
# ============================================================================

class RecognitionStatus(models.TextChoices):
    """认定结果状态（总册 §85）。"""
    PENDING_EFFECTIVE = "PENDING_EFFECTIVE", _("Pending Effective")
    ACTIVE = "ACTIVE", _("Active")
    REVIEW_DUE = "REVIEW_DUE", _("Review Due")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    EXPIRED = "EXPIRED", _("Expired")
    SUSPENDED = "SUSPENDED", _("Suspended")
    REVOKED = "REVOKED", _("Revoked")
    SUPERSEDED = "SUPERSEDED", _("Superseded")
    INVALID = "INVALID", _("Invalid")


# ============================================================================
# Recheck（复核 · 总册 §87-90）
# ============================================================================

class RecheckTrigger(models.TextChoices):
    """复核触发类型（总册 §87）。"""
    SCHEDULED_REVIEW = "SCHEDULED_REVIEW", _("Scheduled Review")
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED", _("Credential Expired")
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED", _("Credential Revoked")
    ETHICS_REVIEW = "ETHICS_REVIEW", _("Ethics Review")
    DATA_CORRECTION = "DATA_CORRECTION", _("Data Correction")
    POLICY_REQUIRED = "POLICY_REQUIRED", _("Policy Required")
    COMPLAINT = "COMPLAINT", _("Complaint")
    AUDIT = "AUDIT", _("Audit")


class RecheckDecision(models.TextChoices):
    """复核决策（总册 §90）。"""
    KEEP = "KEEP", _("Keep")
    UPGRADE = "UPGRADE", _("Upgrade")
    DOWNGRADE = "DOWNGRADE", _("Downgrade")
    SUSPEND = "SUSPEND", _("Suspend")
    REVOKE = "REVOKE", _("Revoke")
    EXPIRE = "EXPIRE", _("Expire")
    NEEDS_FURTHER_REVIEW = "NEEDS_FURTHER_REVIEW", _("Needs Further Review")


# ============================================================================
# Risk（风险 · 总册 §33/§92-93）
# ============================================================================

class RiskType(models.TextChoices):
    """资格/双师风险类型（总册 §33）。"""
    REQUIRED_CREDENTIAL_MISSING = "REQUIRED_CREDENTIAL_MISSING", _("Required Credential Missing")
    CREDENTIAL_UNVERIFIED = "CREDENTIAL_UNVERIFIED", _("Credential Unverified")
    CREDENTIAL_EXPIRING = "CREDENTIAL_EXPIRING", _("Credential Expiring")
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED", _("Credential Expired")
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED", _("Credential Revoked")
    CERTIFICATE_DOCUMENT_MISSING = "CERTIFICATE_DOCUMENT_MISSING", _("Certificate Document Missing")
    VERIFICATION_PROVIDER_ERROR = "VERIFICATION_PROVIDER_ERROR", _("Verification Provider Error")
    DOUBLE_TEACHER_EVIDENCE_INVALIDATED = "DOUBLE_TEACHER_EVIDENCE_INVALIDATED", _("Double Teacher Evidence Invalidated")


class RiskSeverity(models.TextChoices):
    CRITICAL = "CRITICAL", _("Critical")
    HIGH = "HIGH", _("High")
    MEDIUM = "MEDIUM", _("Medium")
    LOW = "LOW", _("Low")


class RiskStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    ACKNOWLEDGED = "ACKNOWLEDGED", _("Acknowledged")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    RESOLVED = "RESOLVED", _("Resolved")
    DISMISSED = "DISMISSED", _("Dismissed")
    CLOSED = "CLOSED", _("Closed")


# ============================================================================
# Renewal（续证 · 总册 §28）
# ============================================================================

class RenewalType(models.TextChoices):
    SAME_LEVEL = "SAME_LEVEL", _("Same Level")
    UPGRADE = "UPGRADE", _("Upgrade")
    CORRECTION = "CORRECTION", _("Correction")


# ============================================================================
# Objection（异议 · 总册 §81）
# ============================================================================

class ObjectionStatus(models.TextChoices):
    RECEIVED = "RECEIVED", _("Received")
    UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
    UPHELD = "UPHELD", _("Upheld")
    CHANGED = "CHANGED", _("Changed")
    REJECTED = "REJECTED", _("Rejected")
    CLOSED = "CLOSED", _("Closed")


# ============================================================================
# Evidence Package（证据包 · 总册 §57）
# ============================================================================

class EvidencePackageStatus(models.TextChoices):
    GENERATING = "GENERATING", _("Generating")
    GENERATED = "GENERATED", _("Generated")
    FROZEN = "FROZEN", _("Frozen")           # 提交后冻结
    SUPERSEDED = "SUPERSEDED", _("Superseded")


# ============================================================================
# Decision Authority（决策权 · 总册 §79-80）
# ============================================================================

class PanelDecisionType(models.TextChoices):
    RECOMMEND_RECOGNIZE = "RECOMMEND_RECOGNIZE", _("Recommend Recognize")
    RECOMMEND_NOT_RECOGNIZE = "RECOMMEND_NOT_RECOGNIZE", _("Recommend Not Recognize")
    ESCALATE = "ESCALATE", _("Escalate")


class FinalDecisionType(models.TextChoices):
    RECOGNIZE = "RECOGNIZE", _("Recognize")
    NOT_RECOGNIZE = "NOT_RECOGNIZE", _("Not Recognize")


# ============================================================================
# 权限码（总册 §125）
# ============================================================================
HR09_PERMISSIONS: tuple[str, ...] = (
    "hr.qualification.credential.view",
    "hr.qualification.credential.create",
    "hr.qualification.credential.verify",
    "hr.qualification.credential.revoke",
    "hr.qualification.credential.sensitive_view",
    "hr.qualification.credential.export",
    "hr.qualification.rule.view",
    "hr.qualification.rule.manage",
    "hr.qualification.rule.publish",
    "hr.qualification.application.self",
    "hr.qualification.application.view",
    "hr.qualification.application.formal_review",
    "hr.qualification.review.score",
    "hr.qualification.review.panel_manage",
    "hr.qualification.review.finalize",
    "hr.qualification.review.final_decision.correct",
    "hr.qualification.review.final_decision.revoke",
    "hr.qualification.recognition.view",
    "hr.qualification.recognition.manage",
    "hr.qualification.recognition.recheck",
    "hr.qualification.recognition.revoke",
    "hr.qualification.risk.view",
    "hr.qualification.risk.manage",
)

# ============================================================================
# 错误码（总册 §112）
# ============================================================================
HR09_ERROR_CODES: frozenset[str] = frozenset(
    {
        "CREDENTIAL_TYPE_INVALID",
        "CREDENTIAL_DUPLICATE",
        "CREDENTIAL_VERIFICATION_REQUIRED",
        "CREDENTIAL_VERIFICATION_FAILED",
        "CREDENTIAL_EXPIRED",
        "CREDENTIAL_REVOKED",
        "RULE_PACK_INVALID",
        "RULE_WEAKER_THAN_PARENT",
        "RULE_VERSION_INACTIVE",
        "EVIDENCE_SOURCE_UNAVAILABLE",
        "EVIDENCE_MISSING",
        "PRECHECK_HARD_RULE_FAILED",
        "APPLICATION_NOT_ELIGIBLE",
        "APPLICATION_ALREADY_SUBMITTED",
        "PANEL_CONFLICT_OF_INTEREST",
        "SCORE_SHEET_ALREADY_LOCKED",
        "FINAL_DECISION_ALREADY_EXISTS",
        "RECOGNITION_RECHECK_REQUIRED",
        "RECOGNITION_DEPENDENCY_INVALIDATED",
        "VERSION_CONFLICT",
        "TENANT_CONTEXT_REQUIRED",
        "CERTIFICATE_NO_EXACT_MATCH_DENIED",
    }
)

# ============================================================================
# Outbox 事件（总册 §119）
# ============================================================================
HR09_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "CredentialSubmitted",
        "CredentialVerified",
        "CredentialExpired",
        "CredentialRevoked",
        "DoubleTeacherBatchPublished",
        "DoubleTeacherApplicationSubmitted",
        "DoubleTeacherEvidenceInvalidated",
        "DoubleTeacherRecognitionGranted",
        "DoubleTeacherRecognitionRecheckDue",
        "DoubleTeacherRecognitionRevoked",
        "QualificationRiskOpened",
        "QualificationResultEffective",
    }
)


# ============================================================================
# Data Scope（总册 §126）
# ============================================================================
class QualificationScopeType(models.TextChoices):
    SCHOOL = "SCHOOL", _("School")
    COLLEGE = "COLLEGE", _("College")
    ORGANIZATION = "ORGANIZATION", _("Organization")
    SELF = "SELF", _("Self")
    BATCH = "BATCH", _("Batch")
    ASSIGNED_APPLICATIONS = "ASSIGNED_APPLICATIONS", _("Assigned Applications")
    PANEL_ASSIGNED = "PANEL_ASSIGNED", _("Panel Assigned")
