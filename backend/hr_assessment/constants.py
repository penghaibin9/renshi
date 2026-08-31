"""
hr_assessment/constants.py —— HR12 公共合同常量（S1 冻结）。

对齐总册：
- §41 考核类型（AssessmentType / AssessmentSubType）
- §40 政策状态（PolicyStatus）
- §44 周期生命周期（CycleLifecycleStatus）
- §6/50 年度考核档次（AnnualGrade）
- §8/51 聘期考核档次（TermGrade）
- §16 证据可信度（TrustLevel）
- §77 评议人角色（ReviewerRole）
- §105 考核 Case 状态（CaseStatus）
- §78 利益冲突状态（ConflictStatus）
- §84 匿名策略（AnonymityStrategy）
- §11 岗位分类（JobClassificationCategory）
- §8.1 特殊人群类型（SpecialPopulationType）
- §183 核心错误码
- §184 权限码（14 个 hr.assessment.*）
- §47 特殊人群类型
- §99 更正类型（RevisionType）
- §93-94 结果状态（ResultStatus）

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# ─── S1.2.1 考核类型 ───

class AssessmentType(models.TextChoices):
    """考核类型 —— 总册 §41 稳定内置枚举。学校通过 AssessmentSubType 扩展。"""

    ANNUAL = "ANNUAL", _("年度考核")
    TERM = "TERM", _("聘期考核")
    ROUTINE = "ROUTINE", _("平时考核")
    SPECIAL = "SPECIAL", _("专项考核")
    ETHICS = "ETHICS", _("师德评价")
    MULTI_RATER = "MULTI_RATER", _("360/多主体评价")


class AssessmentSubType(models.TextChoices):
    """考核子类型 —— 学校可扩展的分类标签，不作为核心状态机驱动。"""

    TEACHER_ANNUAL = "TEACHER_ANNUAL", _("教师年度考核")
    COUNSELOR_ANNUAL = "COUNSELOR_ANNUAL", _("辅导员年度考核")
    ADMIN_ANNUAL = "ADMIN_ANNUAL", _("管理岗年度考核")
    TERM_COMPREHENSIVE = "TERM_COMPREHENSIVE", _("综合聘期考核")
    ETHICS_PERIODIC = "ETHICS_PERIODIC", _("周期性师德评价")
    SPECIAL_TASK = "SPECIAL_TASK", _("专项任务考核")
    SPECIAL_EVENT = "SPECIAL_EVENT", _("特定事件考核")


# ─── S1.2.2 政策状态 ───

class PolicyStatus(models.TextChoices):
    """政策版本状态 —— 总册 §40。PUBLISHED 后 immutable。"""

    DRAFT = "DRAFT", _("草案")
    PUBLISHED = "PUBLISHED", _("已发布")
    RETIRED = "RETIRED", _("已停用")


# ─── S1.2.3 周期生命周期 ───

class CycleLifecycleStatus(models.TextChoices):
    """考核周期生命周期 —— 总册 §44。"""

    DRAFT = "DRAFT", _("草稿")
    VALIDATING = "VALIDATING", _("验证中")
    READY_TO_PUBLISH = "READY_TO_PUBLISH", _("待发布")
    PUBLISHED = "PUBLISHED", _("已发布")
    POPULATION_FREEZING = "POPULATION_FREEZING", _("人群冻结中")
    ACTIVE = "ACTIVE", _("进行中")
    FINALIZING = "FINALIZING", _("审定中")
    CLOSED = "CLOSED", _("已关闭")
    ARCHIVED = "ARCHIVED", _("已归档")
    # 异常状态
    SUSPENDED = "SUSPENDED", _("已暂停")
    CANCELLED = "CANCELLED", _("已取消")
    REOPENED_BY_AUTHORITY = "REOPENED_BY_AUTHORITY", _("有权组织重开")


# ─── S1.2.4 年度考核档次 ───

class AnnualGrade(models.TextChoices):
    """年度考核档次 —— 总册 §6/§50。"""

    EXCELLENT = "EXCELLENT", _("优秀")
    QUALIFIED = "QUALIFIED", _("合格")
    BASICALLY_QUALIFIED = "BASICALLY_QUALIFIED", _("基本合格")
    UNQUALIFIED = "UNQUALIFIED", _("不合格")
    NO_RATING = "NO_RATING", _("不确定档次")
    DEFERRED = "DEFERRED", _("缓定")
    CANCELLED_NOT_RESULT = "CANCELLED_NOT_RESULT", _("取消无结果")


class NoRatingReasonCode(models.TextChoices):
    """NO_RATING 原因码 —— 总册 §47/§114。"""

    NEW_JOINER = "NEW_JOINER", _("新入职")
    TRANSFERRED = "TRANSFERRED", _("调岗")
    LONG_LEAVE = "LONG_LEAVE", _("长期请假")
    RETIRED_DURING = "RETIRED_DURING", _("周期内退休")
    LEFT_DURING = "LEFT_DURING", _("周期内离校")
    EXTERNAL = "EXTERNAL", _("外聘/兼职")
    PART_TIME = "PART_TIME", _("非全职")
    MULTI_ASSIGNMENT = "MULTI_ASSIGNMENT", _("多岗人员")
    DEFERRED_BY_POLICY = "DEFERRED_BY_POLICY", _("按政策缓定")
    SPECIAL_POLICY = "SPECIAL_POLICY", _("特殊政策")
    CANCELLED = "CANCELLED", _("取消考核")


# ─── S1.2.5 聘期考核档次 ───

class TermGrade(models.TextChoices):
    """聘期考核档次 —— 总册 §8/§51。"""

    QUALIFIED = "QUALIFIED", _("合格")
    UNQUALIFIED = "UNQUALIFIED", _("不合格")
    NO_RATING = "NO_RATING", _("不确定档次")
    SPECIAL_POLICY = "SPECIAL_POLICY", _("特殊政策")


# ─── S1.2.6 证据可信度 ───

class TrustLevel(models.TextChoices):
    """证据可信度 —— 总册 §16。统一跨 18 模块的 Provider 状态。"""

    AUTHORITATIVE_VERIFIED = "AUTHORITATIVE_VERIFIED", _("权威核验")
    SYSTEM_VERIFIED = "SYSTEM_VERIFIED", _("系统核验")
    REVIEWER_VERIFIED = "REVIEWER_VERIFIED", _("评议人核验")
    SELF_REPORTED = "SELF_REPORTED", _("自报")
    THIRD_PARTY_UNVERIFIED = "THIRD_PARTY_UNVERIFIED", _("第三方未核验")
    MIGRATED_VERIFIED = "MIGRATED_VERIFIED", _("迁移已核验")
    MIGRATED_UNVERIFIED = "MIGRATED_UNVERIFIED", _("迁移未核验")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("源不可用")


# ─── S1.2.7 评议人角色 ───

class ReviewerRole(models.TextChoices):
    """评议人角色 —— 总册 §77。"""

    SELF = "SELF", _("本人")
    DIRECT_MANAGER = "DIRECT_MANAGER", _("直接主管")
    ORG_HEAD = "ORG_HEAD", _("组织负责人")
    FUNCTIONAL_REVIEWER = "FUNCTIONAL_REVIEWER", _("职能评审")
    PEER = "PEER", _("同级")
    SUBORDINATE = "SUBORDINATE", _("下属")
    SERVICE_RECIPIENT = "SERVICE_RECIPIENT", _("服务对象")
    EXPERT = "EXPERT", _("专家")
    HR_REVIEWER = "HR_REVIEWER", _("人事评审员")
    COLLECTIVE_BODY = "COLLECTIVE_BODY", _("集体审定机构")


# ─── S1.2.8 考核 Case 状态 ───

class CaseStatus(models.TextChoices):
    """考核 Case 状态 —— 总册 §105/§125。年度/聘期/专项公共。"""

    DRAFT = "DRAFT", _("草稿")
    READY = "READY", _("就绪")
    SELF_SUMMARY = "SELF_SUMMARY", _("个人总结")
    REVIEWING = "REVIEWING", _("评审中")
    ORG_REVIEW = "ORG_REVIEW", _("组织评议")
    CALIBRATION = "CALIBRATION", _("校准")
    COLLECTIVE_REVIEW = "COLLECTIVE_REVIEW", _("集体审定")
    PROPOSED = "PROPOSED", _("拟确定")
    PUBLICITY = "PUBLICITY", _("公示")
    FINALIZED = "FINALIZED", _("已审定")
    NOTIFIED = "NOTIFIED", _("已告知")
    ACKNOWLEDGED = "ACKNOWLEDGED", _("已确认")
    ARCHIVED = "ARCHIVED", _("已归档")
    # 异常/回退
    RETURNED = "RETURNED", _("退回补正")
    SUSPENDED = "SUSPENDED", _("已暂停")
    CANCELLED = "CANCELLED", _("已取消")
    UNDER_OBJECTION = "UNDER_OBJECTION", _("异议处理中")
    REOPENED = "REOPENED", _("已重新打开")


# ─── S1.2.9 利益冲突 ───

class ConflictStatus(models.TextChoices):
    """评审人利益冲突状态 —— 总册 §78。"""

    CLEAR = "CLEAR", _("无冲突")
    DECLARED = "DECLARED", _("已申报")
    DETECTED = "DETECTED", _("系统检测到")
    RECUSED = "RECUSED", _("已回避")


# ─── S1.2.10 匿名策略 ───

class AnonymityStrategy(models.TextChoices):
    """匿名评价策略 —— 总册 §84。"""

    IDENTIFIED = "IDENTIFIED", _("实名")
    ANONYMOUS_TO_SUBJECT = "ANONYMOUS_TO_SUBJECT", _("对本人匿名")
    ANONYMOUS_TO_MANAGER = "ANONYMOUS_TO_MANAGER", _("对主管匿名")
    AGGREGATED_ONLY = "AGGREGATED_ONLY", _("仅聚合")
    CONFIDENTIAL_HR_ONLY = "CONFIDENTIAL_HR_ONLY", _("仅HR可查")


# ─── S1.2.11 岗位分类 ───

class JobClassificationCategory(models.TextChoices):
    """高校岗位分类 —— 总册 §11/§48。"""

    TEACHING_FOCUSED = "TEACHING_FOCUSED", _("教学为主型")
    TEACHING_RESEARCH = "TEACHING_RESEARCH", _("教学科研型")
    RESEARCH_FOCUSED = "RESEARCH_FOCUSED", _("科研为主型")
    STUDENT_AFFAIRS = "STUDENT_AFFAIRS", _("辅导员/学生工作")
    LAB_TECHNICAL = "LAB_TECHNICAL", _("实验技术")
    ADMINISTRATION = "ADMINISTRATION", _("管理岗")
    PROFESSIONAL_TECHNICAL_OTHER = "PROFESSIONAL_TECHNICAL_OTHER", _("其他专技")
    WORKER_SKILL = "WORKER_SKILL", _("工勤技能")
    EXTERNAL = "EXTERNAL", _("外聘/兼职")
    OTHER_POLICY = "OTHER_POLICY", _("其他制度规定")


# ─── 特殊人群类型 ───

class SpecialPopulationType(models.TextChoices):
    """特殊人群类型 —— 总册 §47。"""

    NEW_JOINER = "NEW_JOINER", _("新入职")
    TRANSFERRED = "TRANSFERRED", _("调岗")
    SECONDMENT = "SECONDMENT", _("借调外派")
    LONG_LEAVE = "LONG_LEAVE", _("长期请假")
    RETIRED_DURING_PERIOD = "RETIRED_DURING_PERIOD", _("周期内退休")
    LEFT_DURING_PERIOD = "LEFT_DURING_PERIOD", _("周期内离校")
    EXTERNAL = "EXTERNAL", _("外聘/兼职")
    PART_TIME = "PART_TIME", _("非全职")
    MULTI_ASSIGNMENT = "MULTI_ASSIGNMENT", _("多岗")
    NO_RATING_POLICY = "NO_RATING_POLICY", _("按制度不考核")
    DEFERRED = "DEFERRED", _("缓定")


# ─── 指标维度 ───

class IndicatorDimension(models.TextChoices):
    """事业单位考核内容维度 —— 总册 §5。"""

    MORALITY = "MORALITY", _("德")
    CAPABILITY = "CAPABILITY", _("能")
    DILIGENCE = "DILIGENCE", _("勤")
    PERFORMANCE = "PERFORMANCE", _("绩")
    INTEGRITY = "INTEGRITY", _("廉")


# ─── 指标来源 Provider ───

class IndicatorSourceProvider(models.TextChoices):
    """指标数据来源 Provider 类型 —— 总册 §194。"""

    ACADEMIC = "ACADEMIC", _("教务系统")
    RESEARCH = "RESEARCH", _("科研系统")
    HR10_DEVELOPMENT = "HR10_DEVELOPMENT", _("教师发展(HR10)")
    HR11_TIME = "HR11_TIME", _("考勤(HR11)")
    HR09_QUALIFICATION = "HR09_QUALIFICATION", _("教师资格(HR09)")
    ETHICS_FACT = "ETHICS_FACT", _("师德事实")
    SELF_REPORT = "SELF_REPORT", _("自报")
    REVIEWER = "REVIEWER", _("评议人")
    MULTI_RATER = "MULTI_RATER", _("多主体")
    MANUAL_ENTRY = "MANUAL_ENTRY", _("人工录入")


# ─── 评分计算方式 ───

class ScoringMethod(models.TextChoices):
    """评分计算方式 —— 总册 §55。"""

    WEIGHTED_SUM = "WEIGHTED_SUM", _("加权求和")
    THRESHOLD = "THRESHOLD", _("阈值判定")
    LEVEL_MAPPING = "LEVEL_MAPPING", _("等级映射")
    LOOKUP_TABLE = "LOOKUP_TABLE", _("查表")
    HUMAN_PANEL = "HUMAN_PANEL", _("人工评议")
    HYBRID = "HYBRID", _("混合模式")
    NO_NUMERIC_TOTAL = "NO_NUMERIC_TOTAL", _("无数值总分")


# ─── 证据周期语义 ───

class EvidencePeriodSemantic(models.TextChoices):
    """证据周期语义 —— 总册 §74。"""

    WITHIN_CYCLE = "WITHIN_CYCLE", _("周期内")
    WITHIN_TERM = "WITHIN_TERM", _("聘期内")
    AS_OF_DATE = "AS_OF_DATE", _("截至日期")
    CUMULATIVE = "CUMULATIVE", _("累积")
    ROLLING_WINDOW = "ROLLING_WINDOW", _("滑动窗口")
    LIFETIME_REFERENCE = "LIFETIME_REFERENCE", _("终身引用")


# ─── 证据核实状态 ───

class EvidenceVerificationStatus(models.TextChoices):
    """证据核实状态 —— 总册 §72。"""

    PENDING = "PENDING", _("待核实")
    VERIFIED = "VERIFIED", _("已核实")
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED", _("部分核实")
    REJECTED_AS_EVIDENCE = "REJECTED_AS_EVIDENCE", _("不予采信")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("源不可用")
    CONFLICT = "CONFLICT", _("冲突")


# ─── 结果状态 ───

class ResultStatus(models.TextChoices):
    """正式考核结果状态 —— 总册 §94。"""

    DRAFT_RECOMMENDATION = "DRAFT_RECOMMENDATION", _("建议草案")
    PROPOSED = "PROPOSED", _("拟确定")
    FINALIZED = "FINALIZED", _("已审定")
    NOTIFIED = "NOTIFIED", _("已告知")
    ACKNOWLEDGED = "ACKNOWLEDGED", _("已确认")
    UNDER_OBJECTION = "UNDER_OBJECTION", _("异议处理中")
    SUPERSEDED = "SUPERSEDED", _("已取代")
    ARCHIVED = "ARCHIVED", _("已归档")
    VOID_BY_AUTHORITY = "VOID_BY_AUTHORITY", _("有权组织撤销")


# ─── 更正/Revision 类型 ───

class RevisionType(models.TextChoices):
    """结果更正类型 —— 总册 §99。"""

    CORRECTION = "CORRECTION", _("数据纠错")
    REASSESSMENT = "REASSESSMENT", _("重新评价")
    OBJECTION_UPHELD = "OBJECTION_UPHELD", _("异议成立")
    COLLECTIVE_OVERRIDE = "COLLECTIVE_OVERRIDE", _("集体审定调整")
    POLICY_RETROACTIVE = "POLICY_RETROACTIVE", _("制度回溯")


# ─── 异议状态 ───

class ObjectionStatus(models.TextChoices):
    """考核异议/申诉状态 —— 总册 §97。"""

    SUBMITTED = "SUBMITTED", _("已提交")
    ACCEPTED_FOR_REVIEW = "ACCEPTED_FOR_REVIEW", _("已受理")
    RETURNED_FOR_MORE_INFO = "RETURNED_FOR_MORE_INFO", _("退回补材料")
    UNDER_REVIEW = "UNDER_REVIEW", _("复核中")
    UPHELD = "UPHELD", _("异议成立")
    MODIFIED = "MODIFIED", _("部分调整")
    REJECTED = "REJECTED", _("驳回")
    CLOSED = "CLOSED", _("已关闭")


# ─── Hard Gate 状态 ───

class GateStatus(models.TextChoices):
    """硬门槛状态 —— 总册 §13/§18。"""

    PASS = "PASS", _("通过")
    REVIEW_REQUIRED = "REVIEW_REQUIRED", _("需人工审核")
    BLOCKED_BY_FORMAL_FACT = "BLOCKED_BY_FORMAL_FACT", _("正式事实阻断")
    UNAVAILABLE = "UNAVAILABLE", _("源不可用")


# ─── 目标状态 ───

class GoalStatus(models.TextChoices):
    """目标任务状态 —— 总册 §63。"""

    DRAFT = "DRAFT", _("草稿")
    CONFIRMED = "CONFIRMED", _("已确认")
    CHANGE_REQUESTED = "CHANGE_REQUESTED", _("变更申请中")
    APPROVED = "APPROVED", _("已批准变更")
    CANCELLED = "CANCELLED", _("已取消")
    REPLACED = "REPLACED", _("已替换")
    ARCHIVED = "ARCHIVED", _("已归档")


# ─── 目标分配类型 ───

class GoalAssignmentType(models.TextChoices):
    """目标分配类型 —— 总册 §65。"""

    INDIVIDUAL = "INDIVIDUAL", _("个人")
    TEAM = "TEAM", _("团队")
    ORG = "ORG", _("组织")
    ROLE = "ROLE", _("角色")


# ─── 目标来源类型 ───

class GoalSourceType(models.TextChoices):
    """目标来源类型 —— 总册 §61。"""

    POSITION_DUTY = "POSITION_DUTY", _("岗位职责")
    ANNUAL_TASK = "ANNUAL_TASK", _("年度重点任务")
    ORG_DECOMPOSITION = "ORG_DECOMPOSITION", _("学院分解")
    INDIVIDUAL_NEGOTIATION = "INDIVIDUAL_NEGOTIATION", _("个人协商")
    HR07_TERM_GOAL = "HR07_TERM_GOAL", _("HR07 聘期目标")
    SPECIAL_TASK = "SPECIAL_TASK", _("专项任务")


# ─── 进度度量类型 ───

class MeasureType(models.TextChoices):
    """目标度量类型 —— 总册 §64。去除旧 PMS 的 USD/INR/EUR 货币硬编码。"""

    PERCENTAGE = "PERCENTAGE", _("百分比")
    NUMBER = "NUMBER", _("绝对数")
    BOOLEAN = "BOOLEAN", _("是否完成")
    RATING = "RATING", _("评分")
    DESCRIPTIVE = "DESCRIPTIVE", _("描述性")


# ─── 工作流步骤 ───

class WorkflowStepCode(models.TextChoices):
    """考核工作流步骤 —— 总册 §57。"""

    GOAL_CONFIRM = "GOAL_CONFIRM", _("目标确认")
    SELF_SUMMARY = "SELF_SUMMARY", _("个人总结")
    MANAGER_REVIEW = "MANAGER_REVIEW", _("主管评价")
    ORG_REVIEW = "ORG_REVIEW", _("组织评议")
    MULTI_RATER = "MULTI_RATER", _("多主体评价")
    EVIDENCE_VERIFY = "EVIDENCE_VERIFY", _("证据核实")
    CALIBRATION = "CALIBRATION", _("校准")
    COLLECTIVE_DELIBERATION = "COLLECTIVE_DELIBERATION", _("集体审定")
    PUBLICITY = "PUBLICITY", _("公示")
    RESULT_NOTICE = "RESULT_NOTICE", _("结果告知")
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT", _("本人确认")
    OBJECTION_WINDOW = "OBJECTION_WINDOW", _("异议期")
    ARCHIVE = "ARCHIVE", _("归档")


# ─── Provider 状态 ───

class ProviderStatus(models.TextChoices):
    """Provider 状态信封 —— 00 合同 §11。"""

    OK = "OK", _("正常")
    PARTIAL = "PARTIAL", _("部分可用")
    UNAVAILABLE = "UNAVAILABLE", _("不可用")
    STALE = "STALE", _("过期")
    ERROR = "ERROR", _("错误")
    NOT_APPLICABLE = "NOT_APPLICABLE", _("不适用")


# ─── 告知状态 ───

class NoticeDeliveryStatus(models.TextChoices):
    """结果告知送达状态 —— 总册 §95。"""

    PENDING = "PENDING", _("待发送")
    DELIVERED = "DELIVERED", _("已送达")
    VIEWED = "VIEWED", _("已查看")
    FAILED = "FAILED", _("发送失败")


# ─── 本人意见状态 ───

class AcknowledgementStatus(models.TextChoices):
    """本人意见确认状态 —— 总册 §96。"""

    RECEIVED_AGREE = "RECEIVED_AGREE", _("已收到并同意")
    RECEIVED_RESERVATION = "RECEIVED_RESERVATION", _("已收到保留意见")
    RECEIVED_DISAGREE = "RECEIVED_DISAGREE", _("已收到并不同意")
    NOT_DELIVERED = "NOT_DELIVERED", _("未送达")
    NOT_RESPONDED = "NOT_RESPONDED", _("未回复")


# ─── 公示状态 ───

class PublicityStatus(models.TextChoices):
    """公示状态 —— 总册 §111。"""

    DRAFT = "DRAFT", _("待公示")
    ACTIVE = "ACTIVE", _("公示中")
    COMPLETED = "COMPLETED", _("公示完成")
    RESTARTED = "RESTARTED", _("重新公示")


# ─── 档案状态 ───

class ArchiveStatus(models.TextChoices):
    """归档状态 —— 总册 §101。"""

    PENDING = "PENDING", _("待归档")
    ARCHIVING = "ARCHIVING", _("归档中")
    ARCHIVED = "ARCHIVED", _("已归档")
    FAILED = "FAILED", _("归档失败")


# ═══════════════════════════════════════════════
# 核心错误码（总册 §183）
# ═══════════════════════════════════════════════

ASSESSMENT_ERROR_CODES = frozenset(
    {
        "ASSESSMENT_POLICY_NOT_FOUND",
        "ASSESSMENT_POLICY_AMBIGUOUS",
        "ASSESSMENT_POLICY_VERSION_RETIRED",
        "ASSESSMENT_CYCLE_CLOSED",
        "ASSESSMENT_POPULATION_NOT_FROZEN",
        "ASSESSMENT_SUBJECT_INELIGIBLE",
        "ASSESSMENT_REVIEWER_CONFLICT",
        "ASSESSMENT_REQUIRED_REVIEW_MISSING",
        "ASSESSMENT_EVIDENCE_UNAVAILABLE",
        "ASSESSMENT_EVIDENCE_CONFLICT",
        "ASSESSMENT_GATE_BLOCKED",
        "ASSESSMENT_QUOTA_EXCEEDED",
        "ASSESSMENT_PUBLICITY_INCOMPLETE",
        "ASSESSMENT_FINALIZATION_BLOCKED",
        "ASSESSMENT_ALREADY_FINALIZED",
        "ASSESSMENT_RESULT_VERSION_CONFLICT",
        "ASSESSMENT_OBJECTION_ALREADY_OPEN",
        "ASSESSMENT_PROVIDER_UNAVAILABLE",
        "ASSESSMENT_REVIEWER_RESOLUTION_FAILED",
        "ASSESSMENT_TERM_CONTEXT_NOT_FOUND",
        "ASSESSMENT_TERM_INPUT_INCOMPLETE",
        "ASSESSMENT_OVER_QUOTA_BLOCKER",
        "ASSESSMENT_OBJECTION_REVIEWER_UNAVAILABLE",
        "ASSESSMENT_INSUFFICIENT_RESPONSES",
    }
)

# ═══════════════════════════════════════════════
# 权限码（总册 §184 — 14 个）
# ═══════════════════════════════════════════════

ASSESSMENT_PERMISSIONS = (
    ("hr.assessment.policy.admin", _("Policy Pack/Version 管理 — CRUD + publish")),
    ("hr.assessment.cycle.admin", _("周期管理 — lifecycle + population freeze")),
    ("hr.assessment.hr_reviewer", _("校级人事评审员")),
    ("hr.assessment.college_reviewer", _("学院级评审员")),
    ("hr.assessment.manager_reviewer", _("直接主管评审员")),
    ("hr.assessment.panel_member", _("评审委员会成员")),
    ("hr.assessment.calibration_manager", _("校准主持人")),
    ("hr.assessment.final_decider", _("集体审定决策人")),
    ("hr.assessment.ethics_reviewer", _("师德专项评审员")),
    ("hr.assessment.special_reviewer", _("专项任务评审员")),
    ("hr.assessment.archive_manager", _("档案归档管理员")),
    ("hr.assessment.auditor", _("考核审计员")),
    ("hr.assessment.employee_self", _("本人自助 — SELF scope enforced")),
    ("hr.assessment.analytics_view", _("统计分析查看")),
)

# ═══════════════════════════════════════════════
# Data Scope（总册 §185）
# ═══════════════════════════════════════════════

class DataScope(models.TextChoices):
    """考核数据范围 —— 总册 §185。"""

    SELF = "SELF", _("仅本人")
    ASSIGNED_CASES = "ASSIGNED_CASES", _("已分配案例")
    DIRECT_REPORTS = "DIRECT_REPORTS", _("直接下属")
    ORG = "ORG", _("本组织")
    ORG_DESCENDANTS = "ORG_DESCENDANTS", _("本组织及下级")
    COLLEGE = "COLLEGE", _("本学院")
    SCHOOL = "SCHOOL", _("全校")
    AUDIT_SCOPED = "AUDIT_SCOPED", _("审计受限")


# ═══════════════════════════════════════════════
# 事件类型（总册 §193 — 跨域 Outbox Events）
# ═══════════════════════════════════════════════

ASSESSMENT_EVENT_TYPES = frozenset(
    {
        "AssessmentPolicyPublished",
        "AssessmentCycleOpened",
        "AssessmentPopulationFrozen",
        "AssessmentGoalConfirmed",
        "AssessmentGoalRevised",
        "AssessmentCaseStarted",
        "AssessmentSelfReviewSubmitted",
        "AssessmentReviewerAssigned",
        "AssessmentEvaluationSubmitted",
        "AssessmentEvidenceUnavailable",
        "AssessmentCalibrationChanged",
        "AssessmentGradeProposed",
        "AssessmentPublicityStarted",
        "AssessmentPublicityCompleted",
        "AssessmentResultFinalized",
        "AssessmentResultNotified",
        "AssessmentResultAcknowledged",
        "AssessmentObjectionSubmitted",
        "AssessmentObjectionDecided",
        "AssessmentResultRevised",
        "AssessmentArchived",
        "TermAssessmentFinalized",
        "DownstreamAssessmentReviewRequired",
    }
)

# ═══════════════════════════════════════════════
# 敏感数据分级（总册 §190）
# ═══════════════════════════════════════════════

class DataSensitivityLevel(models.TextChoices):
    """考核数据敏感性分级 —— 总册 §190。"""

    PUBLIC_POLICY = "PUBLIC_POLICY", _("公开制度")
    INTERNAL_METRIC = "INTERNAL_METRIC", _("内部指标")
    RESTRICTED_EVALUATION = "RESTRICTED_EVALUATION", _("受限评价")
    CONFIDENTIAL_FEEDBACK = "CONFIDENTIAL_FEEDBACK", _("保密反馈")
    HIGHLY_RESTRICTED_ETHICS = "HIGHLY_RESTRICTED_ETHICS", _("高敏师德")
    FORMAL_RESULT = "FORMAL_RESULT", _("正式结果")


# ═══════════════════════════════════════════════
# 任务状态（异步 Job）
# ═══════════════════════════════════════════════

class JobStatus(models.TextChoices):
    """异步任务状态 —— 00 合同 §32。"""

    PENDING = "PENDING", _("等待执行")
    RUNNING = "RUNNING", _("执行中")
    SUCCESS = "SUCCESS", _("成功")
    PARTIAL_FAILED = "PARTIAL_FAILED", _("部分失败")
    FAILED = "FAILED", _("失败")
    CANCELLED = "CANCELLED", _("已取消")
    EXPIRED = "EXPIRED", _("已过期")
