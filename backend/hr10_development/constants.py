"""
hr10_development/constants.py —— HR10 公共合同常量（S1 冻结）。

对齐总册：
- §24 发展活动分类体系
- §30 发展计划状态机
- §41 Offering/班次
- §49 Training Request 状态机
- §78 企业实践项目状态机
- §137 错误码
- §144 Outbox Events
- §148 权限
- §149 Data Scope

禁止：本文件之外散写魔法字符串作为跨模块合同。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# ============================================================
# 1. 发展活动分类体系（总册 §24）
# ============================================================

class DevelopmentActivityType(models.TextChoices):
    INTERNAL_TRAINING = "INTERNAL_TRAINING", _("校内培训")
    EXTERNAL_TRAINING = "EXTERNAL_TRAINING", _("校外培训")
    ONLINE_LEARNING = "ONLINE_LEARNING", _("线上学习")
    BLENDED_LEARNING = "BLENDED_LEARNING", _("混合研修")
    TEACHING_WORKSHOP = "TEACHING_WORKSHOP", _("教学研讨会")
    DIGITAL_SKILL_TRAINING = "DIGITAL_SKILL_TRAINING", _("数字化能力培训")
    INDUSTRY_TECH_TRAINING = "INDUSTRY_TECH_TRAINING", _("产业技术培训")
    SCHOOL_VISIT = "SCHOOL_VISIT", _("校际参观")
    VISITING_STUDY = "VISITING_STUDY", _("访学研修")
    SHADOWING = "SHADOWING", _("跟岗研修")
    FURTHER_STUDY = "FURTHER_STUDY", _("继续教育")
    DEGREE_STUDY_PROCESS = "DEGREE_STUDY_PROCESS", _("学历提升")
    CERTIFICATION_PREPARATION = "CERTIFICATION_PREPARATION", _("证书备考")
    ENTERPRISE_PRACTICE = "ENTERPRISE_PRACTICE", _("企业实践")
    PRACTICE_BASE_TRAINING = "PRACTICE_BASE_TRAINING", _("实践基地培训")
    RESEARCH_VISIT = "RESEARCH_VISIT", _("科研访学")
    INTERNATIONAL_EXCHANGE = "INTERNATIONAL_EXCHANGE", _("国际交流")
    OTHER = "OTHER", _("其他")


# ============================================================
# 2. Delivery Mode（总册 §39）
# ============================================================

class DeliveryMode(models.TextChoices):
    ONSITE = "ONSITE", _("线下")
    ONLINE_LIVE = "ONLINE_LIVE", _("线上直播")
    ONLINE_ASYNC = "ONLINE_ASYNC", _("线上异步")
    BLENDED = "BLENDED", _("混合式")
    SHADOWING = "SHADOWING", _("跟岗")
    VISITING = "VISITING", _("访学")
    FIELD_PRACTICE = "FIELD_PRACTICE", _("现场实践")
    ENTERPRISE_PRACTICE = "ENTERPRISE_PRACTICE", _("企业实践")
    SELF_DIRECTED_WITH_VERIFICATION = "SELF_DIRECTED_WITH_VERIFICATION", _("自主+核验")


# ============================================================
# 3. 发展计划状态机（总册 §30）
# ============================================================

class PlanLifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    PREPARING = "PREPARING", _("筹备中")
    READY_FOR_REVIEW = "READY_FOR_REVIEW", _("待审核")
    UNDER_REVIEW = "UNDER_REVIEW", _("审核中")
    APPROVED = "APPROVED", _("已批准")
    PUBLISHED = "PUBLISHED", _("已发布")
    ACTIVE = "ACTIVE", _("执行中")
    CLOSING = "CLOSING", _("关闭中")
    CLOSED = "CLOSED", _("已关闭")
    ARCHIVED = "ARCHIVED", _("已归档")
    RETURNED = "RETURNED", _("退回修改")
    REJECTED = "REJECTED", _("已否决")
    CANCELLED = "CANCELLED", _("已取消")
    SUPERSEDED = "SUPERSEDED", _("已被替代")


class PlanVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    FROZEN = "FROZEN", _("已冻结")


# ============================================================
# 4. 培训项目状态机（总册 §36/§38/§41）
# ============================================================

class ProgramLifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    UNDER_REVIEW = "UNDER_REVIEW", _("审核中")
    PUBLISHED = "PUBLISHED", _("已发布")
    ACTIVE = "ACTIVE", _("进行中")
    CLOSING = "CLOSING", _("关闭中")
    CLOSED = "CLOSED", _("已关闭")
    ARCHIVED = "ARCHIVED", _("已归档")
    CANCELLED = "CANCELLED", _("已取消")


class ProgramVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    PUBLISHED = "PUBLISHED", _("已发布")
    SUPERSEDED = "SUPERSEDED", _("已被替代")


class OfferingStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    OPEN = "OPEN", _("报名开放")
    FULL = "FULL", _("已满")
    WAITLIST_OPEN = "WAITLIST_OPEN", _("候补开放")
    CLOSED = "CLOSED", _("已关闭")
    CANCELLED = "CANCELLED", _("已取消")


class CapacityStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", _("有名额")
    FULL = "FULL", _("已满")
    WAITLIST_OPEN = "WAITLIST_OPEN", _("候补开放")
    CLOSED = "CLOSED", _("已关闭")


# ============================================================
# 5. 培训报名与审批状态机（总册 §48-52）
# ============================================================

class RequestLifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    SUBMITTED = "SUBMITTED", _("已提交")
    UNDER_MANAGER_REVIEW = "UNDER_MANAGER_REVIEW", _("主管审核中")
    UNDER_COLLEGE_REVIEW = "UNDER_COLLEGE_REVIEW", _("学院审核中")
    UNDER_HR_REVIEW = "UNDER_HR_REVIEW", _("人事审核中")
    UNDER_BUDGET_REVIEW = "UNDER_BUDGET_REVIEW", _("预算审核中")
    APPROVED = "APPROVED", _("已批准")
    ENROLLMENT_PENDING = "ENROLLMENT_PENDING", _("待报名")
    ENROLLED = "ENROLLED", _("已报名")
    IN_PROGRESS = "IN_PROGRESS", _("进行中")
    COMPLETION_REVIEW = "COMPLETION_REVIEW", _("完成核验中")
    COMPLETED = "COMPLETED", _("已完成")
    ARCHIVED = "ARCHIVED", _("已归档")
    RETURNED = "RETURNED", _("退回修改")
    REJECTED = "REJECTED", _("已否决")
    WITHDRAWN = "WITHDRAWN", _("已撤回")
    CANCELLED = "CANCELLED", _("已取消")
    WAITLISTED = "WAITLISTED", _("候补中")
    NO_SHOW = "NO_SHOW", _("未出席")
    FAILED = "FAILED", _("未通过")


class EnrollmentStatus(models.TextChoices):
    PENDING = "PENDING", _("待确认")
    CONFIRMED = "CONFIRMED", _("已确认")
    WAITLISTED = "WAITLISTED", _("候补中")
    CANCELLED = "CANCELLED", _("已取消")
    NO_SHOW = "NO_SHOW", _("未出席")
    COMPLETED = "COMPLETED", _("已完成")


class SeatStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", _("已确认")
    WAITLISTED = "WAITLISTED", _("候补中")


class RequestType(models.TextChoices):
    INTERNAL_PROGRAM = "INTERNAL_PROGRAM", _("校内项目")
    EXTERNAL_PROGRAM = "EXTERNAL_PROGRAM", _("校外项目")
    FURTHER_STUDY = "FURTHER_STUDY", _("进修")
    TEAM_REQUEST = "TEAM_REQUEST", _("团队申请")


# ============================================================
# 6. 培训完成与核验状态（总册 §55/§67）
# ============================================================

class CompletionStatus(models.TextChoices):
    PASS = "PASS", _("通过")
    FAIL = "FAIL", _("未通过")
    INCOMPLETE = "INCOMPLETE", _("未完成")
    WITHDRAWN = "WITHDRAWN", _("已退出")
    NO_SHOW = "NO_SHOW", _("未出席")


class ParticipationType(models.TextChoices):
    ATTENDED = "ATTENDED", _("已出席")
    LATE = "LATE", _("迟到")
    LEFT_EARLY = "LEFT_EARLY", _("早退")
    ABSENT = "ABSENT", _("缺席")
    EXCUSED = "EXCUSED", _("已请假")
    UNKNOWN = "UNKNOWN", _("未知")


class ParticipationSource(models.TextChoices):
    ONLINE_PROVIDER = "ONLINE_PROVIDER", _("线上平台")
    OFFLINE_SIGNIN = "OFFLINE_SIGNIN", _("线下签到")
    MANUAL = "MANUAL", _("人工记录")
    IMPORT = "IMPORT", _("导入")


# ============================================================
# 7. 通用核验状态（总册 §67/§156）
# ============================================================

class VerificationStatus(models.TextChoices):
    SYSTEM_PROVIDER_VERIFIED = "SYSTEM_PROVIDER_VERIFIED", _("系统Provider核验")
    TRAINING_PROVIDER_VERIFIED = "TRAINING_PROVIDER_VERIFIED", _("培训Provider核验")
    INTERNAL_INSTRUCTOR_VERIFIED = "INTERNAL_INSTRUCTOR_VERIFIED", _("校内讲师核验")
    HR_VERIFIED = "HR_VERIFIED", _("人事核验")
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED", _("文件核验")
    MANUAL_COMMITTEE_VERIFIED = "MANUAL_COMMITTEE_VERIFIED", _("委员会核验")
    MIGRATED_VERIFIED = "MIGRATED_VERIFIED", _("迁移已核验")
    MIGRATED_PARTIAL = "MIGRATED_PARTIAL", _("迁移部分核验")
    MIGRATED_UNVERIFIED = "MIGRATED_UNVERIFIED", _("迁移未核验")
    SELF_REPORTED = "SELF_REPORTED", _("教师自报")
    UNAVAILABLE = "UNAVAILABLE", _("不可用")
    UNKNOWN = "UNKNOWN", _("未知")


class MigrationTrustLevel(models.TextChoices):
    VERIFIED_SOURCE = "VERIFIED_SOURCE", _("已核验来源")
    DOCUMENT_BACKED = "DOCUMENT_BACKED", _("文件支持")
    ADMIN_CONFIRMED = "ADMIN_CONFIRMED", _("管理员确认")
    MIGRATED_STRUCTURED = "MIGRATED_STRUCTURED", _("结构化迁移")
    MIGRATED_FREE_TEXT = "MIGRATED_FREE_TEXT", _("自由文本迁移")
    SELF_REPORTED = "SELF_REPORTED", _("教师自报")
    UNKNOWN = "UNKNOWN", _("未知")


# ============================================================
# 8. 企业实践项目状态机（总册 §78）
# ============================================================

class ProjectLifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    DESIGNING = "DESIGNING", _("设计中")
    READY_FOR_REVIEW = "READY_FOR_REVIEW", _("待审核")
    APPROVED = "APPROVED", _("已批准")
    PUBLISHED = "PUBLISHED", _("已发布")
    MATCHING = "MATCHING", _("匹配中")
    READY_TO_START = "READY_TO_START", _("准备启动")
    ACTIVE = "ACTIVE", _("进行中")
    COMPLETION_REVIEW = "COMPLETION_REVIEW", _("完成核验中")
    COMPLETED = "COMPLETED", _("已完成")
    CLOSED = "CLOSED", _("已关闭")
    ARCHIVED = "ARCHIVED", _("已归档")
    RETURNED = "RETURNED", _("退回修改")
    REJECTED = "REJECTED", _("已否决")
    SUSPENDED = "SUSPENDED", _("已暂停")
    CANCELLED = "CANCELLED", _("已取消")
    TERMINATED_EARLY = "TERMINATED_EARLY", _("提前终止")


class AssignmentStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    SUBMITTED = "SUBMITTED", _("已提交")
    APPROVED = "APPROVED", _("已批准")
    REJECTED = "REJECTED", _("已否决")
    IN_PROGRESS = "IN_PROGRESS", _("进行中")
    SUSPENDED = "SUSPENDED", _("已暂停")
    COMPLETION_REVIEW = "COMPLETION_REVIEW", _("完成核验中")
    COMPLETED = "COMPLETED", _("已完成")
    CANCELLED = "CANCELLED", _("已取消")
    TERMINATED_EARLY = "TERMINATED_EARLY", _("提前终止")


class PracticeEvaluationStatus(models.TextChoices):
    PASS = "PASS", _("通过")
    FAIL = "FAIL", _("未通过")
    INCOMPLETE = "INCOMPLETE", _("未完成")
    EARLY_TERMINATED = "EARLY_TERMINATED", _("提前终止")


class PracticeActivityType(models.TextChoices):
    OBSERVATION = "OBSERVATION", _("考察观摩")
    POSITION_WORK = "POSITION_WORK", _("岗位操作")
    TECHNICAL_TRAINING = "TECHNICAL_TRAINING", _("技能培训")
    PRODUCTION_TASK = "PRODUCTION_TASK", _("生产任务")
    SERVICE_TASK = "SERVICE_TASK", _("服务任务")
    R_AND_D = "R_AND_D", _("研发")
    TECHNICAL_IMPROVEMENT = "TECHNICAL_IMPROVEMENT", _("技术改进")
    QUALITY_ACTIVITY = "QUALITY_ACTIVITY", _("质量活动")
    PROJECT_MEETING = "PROJECT_MEETING", _("项目会议")
    EMPLOYEE_TRAINING_DELIVERY = "EMPLOYEE_TRAINING_DELIVERY", _("员工培训授课")
    STUDENT_PRACTICE_GUIDANCE = "STUDENT_PRACTICE_GUIDANCE", _("学生实践指导")
    TEACHING_TRANSFORMATION = "TEACHING_TRANSFORMATION", _("教学转化")
    OTHER = "OTHER", _("其他")


class EvidenceSource(models.TextChoices):
    ENTERPRISE_SYSTEM = "ENTERPRISE_SYSTEM", _("企业系统")
    ENTERPRISE_SIGNED_DOCUMENT = "ENTERPRISE_SIGNED_DOCUMENT", _("企业签字盖章")
    PROVIDER_API = "PROVIDER_API", _("Provider 接口")
    MENTOR_DIRECT = "MENTOR_DIRECT", _("企业导师直接提交")
    SCHOOL_CHECK = "SCHOOL_CHECK", _("学校检查")
    MANUAL_COMMITTEE = "MANUAL_COMMITTEE", _("专家委员会")
    SELF_SIGNED_LEDGER = "SELF_SIGNED_LEDGER", _("教师手签+照片")
    SELF_NARRATIVE = "SELF_NARRATIVE", _("教师文字自述")
    IMPORT_STRUCTURED = "IMPORT_STRUCTURED", _("结构化导入")
    IMPORT_FREE_TEXT = "IMPORT_FREE_TEXT", _("自由文本导入")
    MIGRATED_DOCUMENT = "MIGRATED_DOCUMENT", _("迁移文档")
    EXTERNAL_REF = "EXTERNAL_REF", _("外部系统引用")


class EvidenceTrustLevel(models.IntegerChoices):
    AUTHORITY_VERIFIED = 5, _("Authority核验")
    PROVIDER_VERIFIED = 4, _("Provider核验")
    DOCUMENT_VERIFIED = 3, _("文档核验")
    MANUAL_VERIFIED = 2, _("人工核验")
    SELF_REPORTED = 1, _("教师自报")
    MIGRATED_UNVERIFIED = 0, _("迁移未核验")


# ============================================================
# 9. 发展事实类型（总册 §111）
# ============================================================

class FactType(models.TextChoices):
    TRAINING_COMPLETION = "TRAINING_COMPLETION", _("培训完成")
    FURTHER_STUDY = "FURTHER_STUDY", _("进修")
    ENTERPRISE_PRACTICE = "ENTERPRISE_PRACTICE", _("企业实践")
    DEVELOPMENT_OUTPUT = "DEVELOPMENT_OUTPUT", _("发展成果")


# ============================================================
# 10. Provider 机构相关（总册 §25/§44）
# ============================================================

class ProviderKind(models.TextChoices):
    SCHOOL = "SCHOOL", _("其他学校")
    UNIVERSITY = "UNIVERSITY", _("大学")
    ENTERPRISE = "ENTERPRISE", _("企业")
    GOVERNMENT = "GOVERNMENT", _("政府机构")
    ASSOCIATION = "ASSOCIATION", _("行业协会")
    TRAINING_ORG = "TRAINING_ORG", _("培训机构")
    RESEARCH_INST = "RESEARCH_INST", _("科研院所")
    INTERNATIONAL_ORG = "INTERNATIONAL_ORG", _("国际组织")
    OTHER = "OTHER", _("其他")


class ProviderVerificationStatus(models.TextChoices):
    PENDING = "PENDING", _("待核验")
    VERIFIED = "VERIFIED", _("已核验")
    EXPIRED = "EXPIRED", _("已过期")
    REVOKED = "REVOKED", _("已撤销")
    BLACKLISTED = "BLACKLISTED", _("黑名单")
    DEREGISTERED = "DEREGISTERED", _("已退出")


class PracticeBaseLevel(models.TextChoices):
    NATIONAL = "NATIONAL", _("国家级")
    PROVINCIAL = "PROVINCIAL", _("省级")
    SCHOOL_LEVEL = "SCHOOL_LEVEL", _("校级")
    OTHER = "OTHER", _("其他")
    NONE = "NONE", _("非基地")


class RiskStatus(models.TextChoices):
    LOW = "LOW", _("低风险")
    MEDIUM = "MEDIUM", _("中风险")
    HIGH = "HIGH", _("高风险")
    CLOSED = "CLOSED", _("已关闭")
    SUSPENDED = "SUSPENDED", _("已暂停")


# ============================================================
# 11. 进修相关（总册 §57/§58）
# ============================================================

class StudyType(models.TextChoices):
    VISITING = "VISITING", _("访学")
    NON_DEGREE = "NON_DEGREE", _("非学历进修")
    DEGREE = "DEGREE", _("学历提升")
    CERTIFICATE_PROGRAM = "CERTIFICATE_PROGRAM", _("证书项目")
    RESEARCH_VISIT = "RESEARCH_VISIT", _("科研访学")


class MilestoneType(models.TextChoices):
    ADMITTED = "ADMITTED", _("已录取")
    REGISTERED = "REGISTERED", _("已注册")
    MID_REVIEW = "MID_REVIEW", _("中期考核")
    COURSE_COMPLETED = "COURSE_COMPLETED", _("课程完成")
    THESIS = "THESIS", _("论文答辩")
    GRADUATED = "GRADUATED", _("已毕业")
    CERTIFICATE_RECEIVED = "CERTIFICATE_RECEIVED", _("证书获取")
    RETURNED_TO_POST = "RETURNED_TO_POST", _("回岗报到")


# ============================================================
# 12. 成果类型（总册 §96-98）
# ============================================================

class OutputType(models.TextChoices):
    COURSE_CONTENT_UPDATE = "COURSE_CONTENT_UPDATE", _("课程内容更新")
    TRAINING_PROJECT = "TRAINING_PROJECT", _("培训项目")
    PRACTICE_TASK = "PRACTICE_TASK", _("实践任务")
    CASE_LIBRARY = "CASE_LIBRARY", _("案例库")
    TEACHING_RESOURCE = "TEACHING_RESOURCE", _("教学资源")
    TEXTBOOK_MATERIAL = "TEXTBOOK_MATERIAL", _("教材材料")
    CURRICULUM_REVISION = "CURRICULUM_REVISION", _("课程修订")
    STUDENT_PROJECT = "STUDENT_PROJECT", _("学生项目")
    LAB_OR_WORKSHOP_IMPROVEMENT = "LAB_OR_WORKSHOP_IMPROVEMENT", _("实验室/车间改进")
    TECHNICAL_REPORT = "TECHNICAL_REPORT", _("技术报告")
    PROCESS_IMPROVEMENT = "PROCESS_IMPROVEMENT", _("流程改进")
    PRODUCT_OR_SERVICE_PROTOTYPE = "PRODUCT_OR_SERVICE_PROTOTYPE", _("产品/服务原型")
    ENTERPRISE_TRAINING = "ENTERPRISE_TRAINING", _("企业培训")
    TECHNICAL_SERVICE = "TECHNICAL_SERVICE", _("技术服务")
    PATENT_REF = "PATENT_REF", _("专利引用")
    SOFTWARE_COPYRIGHT_REF = "SOFTWARE_COPYRIGHT_REF", _("软件著作权引用")
    STANDARD_REF = "STANDARD_REF", _("标准引用")
    R_AND_D_PROJECT_REF = "R_AND_D_PROJECT_REF", _("研发项目引用")
    OTHER = "OTHER", _("其他")


class OutputVerificationStatus(models.TextChoices):
    SELF_REPORTED = "SELF_REPORTED", _("教师自报")
    SUBMITTED = "SUBMITTED", _("已提交")
    UNDER_VERIFICATION = "UNDER_VERIFICATION", _("核验中")
    VERIFIED = "VERIFIED", _("已核验")
    REJECTED = "REJECTED", _("已退回")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("来源不可用")
    SUPERSEDED = "SUPERSEDED", _("已被替代")


# ============================================================
# 13. 需求类型（总册 §28）
# ============================================================

class NeedSourceType(models.TextChoices):
    SELF = "SELF", _("教师自评")
    MANAGER = "MANAGER", _("主管建议")
    HR = "HR", _("人事建议")
    HR12 = "HR12", _("考核反馈")
    ACADEMIC = "ACADEMIC", _("教务反馈")
    POLICY = "POLICY", _("政策要求")
    SKILL_GAP = "SKILL_GAP", _("能力缺口分析")
    OTHER = "OTHER", _("其他")


# ============================================================
# 14. 计划类型（总册 §26）
# ============================================================

class PlanType(models.TextChoices):
    SCHOOL = "SCHOOL", _("校级计划")
    COLLEGE = "COLLEGE", _("院级计划")
    TEAM = "TEAM", _("团队计划")
    INDIVIDUAL = "INDIVIDUAL", _("个人计划")


class CycleType(models.TextChoices):
    ANNUAL = "ANNUAL", _("年度")
    MULTI_YEAR = "MULTI_YEAR", _("多年期")
    CUSTOM = "CUSTOM", _("自定义")


class TargetUnit(models.TextChoices):
    HOURS = "HOURS", _("学时")
    DAYS = "DAYS", _("天数")
    MONTHS = "MONTHS", _("月数")
    CREDITS = "CREDITS", _("学分")
    COUNT = "COUNT", _("次数")


# ============================================================
# 15. 合规规则（总册 §86）
# ============================================================

class TimeWindowType(models.TextChoices):
    ROLLING_5_YEAR = "ROLLING_5_YEAR", _("滚动5年")
    FIXED_CYCLE = "FIXED_CYCLE", _("固定周期")
    CALENDAR_YEAR = "CALENDAR_YEAR", _("自然年")
    BEFORE_ONBOARDING = "BEFORE_ONBOARDING", _("入职前")
    BEFORE_PROMOTION = "BEFORE_PROMOTION", _("晋升前")


# ============================================================
# 16. 风险中心（总册 §122/§104）
# ============================================================

class RiskType(models.TextChoices):
    MANDATORY_TRAINING_OVERDUE = "MANDATORY_TRAINING_OVERDUE", _("必修培训逾期")
    PRACTICE_COMPLIANCE_DUE = "PRACTICE_COMPLIANCE_DUE", _("实践合规在即")
    PRACTICE_COMPLIANCE_OVERDUE = "PRACTICE_COMPLIANCE_OVERDUE", _("实践合规逾期")
    MISSING_COMPLETION_EVIDENCE = "MISSING_COMPLETION_EVIDENCE", _("缺失完成证据")
    PROVIDER_RISK = "PROVIDER_RISK", _("Provider 风险")
    OPEN_SAFETY_INCIDENT = "OPEN_SAFETY_INCIDENT", _("未关闭安全事件")
    BUDGET_OVERCOMMIT = "BUDGET_OVERCOMMIT", _("预算超承诺")
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT", _("时间冲突")
    UNVERIFIED_EXTERNAL_LEARNING = "UNVERIFIED_EXTERNAL_LEARNING", _("外部学习未核验")
    STALE_MIGRATED_FACT = "STALE_MIGRATED_FACT", _("迁移事实陈旧")
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE", _("重复证据")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("数据源不可用")


class RiskCaseStatus(models.TextChoices):
    OPEN = "OPEN", _("打开")
    ACKNOWLEDGED = "ACKNOWLEDGED", _("已确认")
    IN_PROGRESS = "IN_PROGRESS", _("处理中")
    RESOLVED = "RESOLVED", _("已解决")
    WAIVED = "WAIVED", _("已豁免")


class RiskSeverity(models.TextChoices):
    CRITICAL = "CRITICAL", _("严重")
    HIGH = "HIGH", _("高")
    MEDIUM = "MEDIUM", _("中")
    LOW = "LOW", _("低")


# ============================================================
# 17. 度量指标（总册 §35/§124）
# ============================================================

class MetricCode(models.TextChoices):
    TRAINING_COVERAGE_RATE = "TRAINING_COVERAGE_RATE", _("培训覆盖率")
    MANDATORY_COMPLETION_RATE = "MANDATORY_COMPLETION_RATE", _("必修完成率")
    AVG_VERIFIED_TRAINING_HOURS = "AVG_VERIFIED_TRAINING_HOURS", _("人均已核验培训学时")
    ENTERPRISE_PRACTICE_COVERAGE_RATE = "ENTERPRISE_PRACTICE_COVERAGE_RATE", _("企业实践覆盖率")
    PRACTICE_COMPLIANCE_RATE = "PRACTICE_COMPLIANCE_RATE", _("实践合规率")
    DEVELOPMENT_PLAN_COMPLETION_RATE = "DEVELOPMENT_PLAN_COMPLETION_RATE", _("发展计划完成率")
    OUTPUT_TRANSFORMATION_RATE = "OUTPUT_TRANSFORMATION_RATE", _("成果转化率")
    BUDGET_UTILIZATION_RATE = "BUDGET_UTILIZATION_RATE", _("预算使用率")
    OVERDUE_REQUEST_RATE = "OVERDUE_REQUEST_RATE", _("逾期申请率")


# ============================================================
# 18. 调度冲突检查结果（总册 §63）
# ============================================================

class ScheduleConflictResult(models.TextChoices):
    PASS = "PASS", _("无冲突")
    WARNING = "WARNING", _("有冲突警告")
    BLOCKED = "BLOCKED", _("冲突阻止")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("来源不可用")


# ============================================================
# 19. 错误码（总册 §137）
# ============================================================

class DevelopmentErrorCode(models.TextChoices):
    INVALID_REQUEST = "INVALID_REQUEST", _("请求参数无效")
    TENANT_CONTEXT_REQUIRED = "TENANT_CONTEXT_REQUIRED", _("缺少租户上下文")
    DEVELOPMENT_PLAN_VERSION_CONFLICT = "DEVELOPMENT_PLAN_VERSION_CONFLICT", _("计划版本冲突")
    DEVELOPMENT_PLAN_NOT_PUBLISHED = "DEVELOPMENT_PLAN_NOT_PUBLISHED", _("计划未发布")
    DEVELOPMENT_POLICY_BLOCKED = "DEVELOPMENT_POLICY_BLOCKED", _("政策限制")
    PROGRAM_VERSION_INVALID = "PROGRAM_VERSION_INVALID", _("项目版本无效")
    OFFERING_NOT_OPEN = "OFFERING_NOT_OPEN", _("班次未开放报名")
    OFFERING_CAPACITY_FULL = "OFFERING_CAPACITY_FULL", _("班次名额已满")
    WAITLIST_FULL = "WAITLIST_FULL", _("候补已满")
    DUPLICATE_ENROLLMENT = "DUPLICATE_ENROLLMENT", _("重复报名")
    REQUEST_ALREADY_FINAL = "REQUEST_ALREADY_FINAL", _("申请已终结")
    REQUEST_APPROVAL_SCOPE_DENIED = "REQUEST_APPROVAL_SCOPE_DENIED", _("审批范围拒绝")
    SELF_APPROVAL_NOT_ALLOWED = "SELF_APPROVAL_NOT_ALLOWED", _("禁止自审批")
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT", _("时间冲突")
    SCHEDULE_SOURCE_UNAVAILABLE = "SCHEDULE_SOURCE_UNAVAILABLE", _("排程数据不可用")
    BUDGET_INSUFFICIENT = "BUDGET_INSUFFICIENT", _("预算不足")
    BUDGET_VERSION_CONFLICT = "BUDGET_VERSION_CONFLICT", _("预算版本冲突")
    PROVIDER_NOT_VERIFIED = "PROVIDER_NOT_VERIFIED", _("Provider 未核验")
    PROVIDER_RISK_BLOCKED = "PROVIDER_RISK_BLOCKED", _("Provider 风险拦截")
    PRACTICE_PREREQUISITE_MISSING = "PRACTICE_PREREQUISITE_MISSING", _("实践前置条件未满足")
    PRACTICE_ALREADY_STARTED = "PRACTICE_ALREADY_STARTED", _("实践已开始")
    PRACTICE_TRANSFER_CONFLICT = "PRACTICE_TRANSFER_CONFLICT", _("实践转岗冲突")
    PRACTICE_DURATION_INVALID = "PRACTICE_DURATION_INVALID", _("实践时长无效")
    PRACTICE_EVIDENCE_INVALID = "PRACTICE_EVIDENCE_INVALID", _("证据无效")
    MENTOR_SCOPE_DENIED = "MENTOR_SCOPE_DENIED", _("导师权限拒绝")
    COMPLETION_RULE_NOT_MET = "COMPLETION_RULE_NOT_MET", _("完成规则未满足")
    COMPLETION_ALREADY_VERIFIED = "COMPLETION_ALREADY_VERIFIED", _("完成已核验")
    COMPLETION_REVISION_REQUIRED = "COMPLETION_REVISION_REQUIRED", _("需要修订")
    EXTERNAL_SOURCE_UNAVAILABLE = "EXTERNAL_SOURCE_UNAVAILABLE", _("外部数据不可用")
    DEVELOPMENT_FACT_NOT_VERIFIED = "DEVELOPMENT_FACT_NOT_VERIFIED", _("发展事实未核验")
    TENANT_SCOPE_DENIED = "TENANT_SCOPE_DENIED", _("租户权限拒绝")
    VERSION_CONFLICT = "VERSION_CONFLICT", _("版本冲突")
    PERSON_PROVIDER_UNAVAILABLE = "PERSON_PROVIDER_UNAVAILABLE", _("人员数据不可用")
    NOT_FOUND = "NOT_FOUND", _("资源不存在")


# ============================================================
# 20. Outbox 事件类型（总册 §144，对齐 00 §28.3）
# ============================================================

class DevelopmentEventType(models.TextChoices):
    DevelopmentPlanPublished = "DevelopmentPlanPublished", _("发展计划发布")
    DevelopmentNeedCreated = "DevelopmentNeedCreated", _("发展需求创建")
    LearningProgramPublished = "LearningProgramPublished", _("培训项目发布")
    LearningOfferingOpened = "LearningOfferingOpened", _("班次开放报名")
    TrainingRequestSubmitted = "TrainingRequestSubmitted", _("培训申请提交")
    TrainingRequestApproved = "TrainingRequestApproved", _("培训申请批准")
    TrainingRequestReturned = "TrainingRequestReturned", _("培训申请退回")
    TrainingRequestRejected = "TrainingRequestRejected", _("培训申请否决")
    LearningEnrollmentCreated = "LearningEnrollmentCreated", _("培训报名创建")
    LearningWaitlisted = "LearningWaitlisted", _("进入候补")
    LearningStarted = "LearningStarted", _("培训开始")
    LearningCompletionSubmitted = "LearningCompletionSubmitted", _("完成提交")
    LearningCompletionVerified = "LearningCompletionVerified", _("完成核验通过")
    FurtherStudyStarted = "FurtherStudyStarted", _("进修开始")
    FurtherStudyMilestoneVerified = "FurtherStudyMilestoneVerified", _("进修里程碑核验")
    PracticeProjectPublished = "PracticeProjectPublished", _("企业实践项目发布")
    PracticeAssignmentCreated = "PracticeAssignmentCreated", _("实践派出创建")
    PracticeAssignmentStarted = "PracticeAssignmentStarted", _("实践开始")
    PracticeAssignmentSuspended = "PracticeAssignmentSuspended", _("实践暂停")
    PracticeAssignmentResumed = "PracticeAssignmentResumed", _("实践恢复")
    PracticeAssignmentTransferred = "PracticeAssignmentTransferred", _("实践转岗")
    PracticeEvidenceSubmitted = "PracticeEvidenceSubmitted", _("实践证据提交")
    PracticeEvaluationFinalized = "PracticeEvaluationFinalized", _("实践评价终审")
    DevelopmentOutputVerified = "DevelopmentOutputVerified", _("发展成果核验通过")
    DevelopmentFactVerified = "DevelopmentFactVerified", _("发展事实核验通过")  # 00 §28.3 canonical
    DevelopmentFactSuperseded = "DevelopmentFactSuperseded", _("发展事实被替代")
    DevelopmentRiskOpened = "DevelopmentRiskOpened", _("发展风险开启")
    DevelopmentRiskResolved = "DevelopmentRiskResolved", _("发展风险解决")


# ============================================================
# 21. 权限码（总册 §148、00 §28.2 Prefix: hr.development）
# ============================================================

class DevelopmentPermissionCode(models.TextChoices):
    DEVELOPMENT_ADMIN = "hr.development.admin", _("发展管理")
    PLAN_MANAGER = "hr.development.plan.manage", _("计划管理")
    PLAN_VIEW = "hr.development.plan.view", _("计划查看")
    PROGRAM_MANAGER = "hr.development.program.manage", _("项目管理")
    PROGRAM_VIEW = "hr.development.program.view", _("项目查看")
    APPROVER = "hr.development.approval.review", _("审批")
    BUDGET_REVIEWER = "hr.development.budget.review", _("预算审核")
    PRACTICE_MANAGER = "hr.development.practice.manage", _("实践管理")
    PRACTICE_VIEW = "hr.development.practice.view", _("实践查看")
    COMPLETION_VERIFIER = "hr.development.completion.verify", _("完成核验")
    TEACHER_SELF = "hr.development.self", _("教师本人")
    MENTOR_SCOPED = "hr.development.mentor.scoped", _("企业导师(限定)")
    READ_ANALYTICS = "hr.development.analytics.read", _("分析查看")
    AUDITOR = "hr.development.audit", _("审计")


# ============================================================
# 22. Data Scope（总册 §149）
# ============================================================

class DevelopmentDataScope(models.TextChoices):
    SELF = "SELF", _("本人")
    TEAM = "TEAM", _("团队")
    ORGANIZATION = "ORGANIZATION", _("部门")
    COLLEGE = "COLLEGE", _("学院")
    MANAGED_PROGRAM = "MANAGED_PROGRAM", _("所管项目")
    MANAGED_PRACTICE_PROJECT = "MANAGED_PRACTICE_PROJECT", _("所管实践项目")
    TENANT = "TENANT", _("全校")
    PLATFORM_AGGREGATE_NO_PII = "PLATFORM_AGGREGATE_NO_PII", _("平台聚合(无PII)")


# ============================================================
# 23. 权威模式（对齐 00 §56 Cutover）
# ============================================================

class DevelopmentAuthorityMode(models.TextChoices):
    LEGACY_OR_NONE = "LEGACY_OR_NONE", _("旧模式/无")
    HR10_STAGING = "HR10_STAGING", _("HR10 暂存")
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("双读对比")
    HR10_AUTHORITY = "HR10_AUTHORITY", _("HR10 权威")
    LEGACY_READONLY = "LEGACY_READONLY", _("旧系统只读")


# ============================================================
# 24. Data Freshness（总册 §142）
# ============================================================

class DataFreshnessStatus(models.TextChoices):
    FRESH = "FRESH", _("新鲜")
    STALE = "STALE", _("陈旧")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("来源不可用")


# ============================================================
# 25. 文件安全级别（总册 §146/§147）
# ============================================================

class EvidenceSensitivity(models.TextChoices):
    INTERNAL = "INTERNAL", _("内部")
    PERSONAL = "PERSONAL", _("个人")
    SENSITIVE_PERSONAL = "SENSITIVE_PERSONAL", _("高敏个人")
    RESTRICTED = "RESTRICTED", _("受限")
