"""
hr_time/enums.py

HR11 基础枚举/目录（总册 §8/§24/§31/§61/§73/§83/§88/§99/§113/§123）。

规则：
- 枚举 code 一旦冻结稳定，学校可扩展但不得改已发布 code；
- 业务适用（如某假别规则）一律走 RuleVersion，禁止在这里 if leave_type == ...。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


# ──────────────────────────────────────────────────────────────────────
# 记录方式（总册 §8/§24）
# ──────────────────────────────────────────────────────────────────────
class RecordingMethod(models.TextChoices):
    FIXED_POSITIVE_TIME = "FIXED_POSITIVE_TIME", _("固定班次，完整打卡")
    FLEXIBLE_POSITIVE_TIME = "FLEXIBLE_POSITIVE_TIME", _("弹性时段，记录实际工时")
    NEGATIVE_TIME = "NEGATIVE_TIME", _("默认按计划工作，仅记录偏差")
    ABSENCE_ONLY = "ABSENCE_ONLY", _("只管理请假/缺勤")
    OVERTIME_ONLY = "OVERTIME_ONLY", _("只记录批准加班")
    DUTY_BASED = "DUTY_BASED", _("按职责/任务核验，非每日坐班")
    HYBRID = "HYBRID", _("多种模式组合")


# ──────────────────────────────────────────────────────────────────────
# 政策状态（总册 §27）
# ──────────────────────────────────────────────────────────────────────
class PolicyStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    PUBLISHED = "PUBLISHED", _("已发布")
    RETIRED = "RETIRED", _("已退役")


# ──────────────────────────────────────────────────────────────────────
# 日历类型与日类型（总册 §29/§31）
# ──────────────────────────────────────────────────────────────────────
class CalendarType(models.TextChoices):
    NATIONAL_BASE = "NATIONAL_BASE", _("国家法定基线")
    REGIONAL = "REGIONAL", _("地方日历")
    SCHOOL_ADMIN = "SCHOOL_ADMIN", _("学校行政日历")
    SCHOOL_TEACHER = "SCHOOL_TEACHER", _("学校教师日历")
    SHIFT_OPERATION = "SHIFT_OPERATION", _("轮班运营日历")
    CUSTOM = "CUSTOM", _("自定义")


class CalendarDayType(models.TextChoices):
    REGULAR_WORKDAY = "REGULAR_WORKDAY", _("普通工作日")
    REST_DAY = "REST_DAY", _("休息日")
    STATUTORY_HOLIDAY = "STATUTORY_HOLIDAY", _("法定节假日")
    MAKEUP_WORKDAY = "MAKEUP_WORKDAY", _("调休工作日")
    SCHOOL_BREAK = "SCHOOL_BREAK", _("寒暑假")
    SPECIAL_CLOSURE = "SPECIAL_CLOSURE", _("特殊关闭")
    PARTIAL_HOLIDAY = "PARTIAL_HOLIDAY", _("部分公民放假")


# ──────────────────────────────────────────────────────────────────────
# 原始事件（总册 §51/§59）
# ──────────────────────────────────────────────────────────────────────
class TimeEventType(models.TextChoices):
    IN = "IN", _("签到")
    OUT = "OUT", _("签退")
    BREAK_IN = "BREAK_IN", _("休息开始")
    BREAK_OUT = "BREAK_OUT", _("休息结束")


class TimeEventSourceType(models.TextChoices):
    BIOMETRIC = "BIOMETRIC", _("生物识别设备")
    MOBILE = "MOBILE", _("移动端")
    WEB = "WEB", _("Web 端")
    API = "API", _("系统 API")
    IMPORT = "IMPORT", _("批量导入")
    MANUAL = "MANUAL", _("人工补录")


class TimeEventIngestStatus(models.TextChoices):
    RECEIVED = "RECEIVED", _("已接收")
    VALIDATED = "VALIDATED", _("已验证")
    PERSON_UNMAPPED = "PERSON_UNMAPPED", _("人员未映射")
    DUPLICATE = "DUPLICATE", _("重复")
    REJECTED = "REJECTED", _("拒绝")
    STAGED = "STAGED", _("待人工处理")


class PairingStatus(models.TextChoices):
    PAIRED = "PAIRED", _("已配对")
    OPEN = "OPEN", _("待配对")
    AMBIGUOUS = "AMBIGUOUS", _("配对歧义")
    INVALID_ORDER = "INVALID_ORDER", _("顺序异常")
    CROSS_SHIFT = "CROSS_SHIFT", _("跨班次")
    MANUAL_REVIEW = "MANUAL_REVIEW", _("人工复核")


# ──────────────────────────────────────────────────────────────────────
# 考勤事实状态（总册 §61：禁止只用 P/A/L）
# ──────────────────────────────────────────────────────────────────────
class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", _("出勤")
    PARTIAL_PRESENT = "PARTIAL_PRESENT", _("部分出勤")
    AUTHORIZED_ABSENCE = "AUTHORIZED_ABSENCE", _("授权缺勤")
    AUTHORIZED_DUTY = "AUTHORIZED_DUTY", _("授权公务/外勤")
    REST_DAY = "REST_DAY", _("休息日")
    STATUTORY_HOLIDAY = "STATUTORY_HOLIDAY", _("法定节假日")
    MISSING_TIME = "MISSING_TIME", _("缺卡待核查")
    PENDING_REVIEW = "PENDING_REVIEW", _("待复核")
    UNEXCUSED_ABSENCE = "UNEXCUSED_ABSENCE", _("未授权缺勤候选")
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", _("数据源不可用")
    NOT_APPLICABLE = "NOT_APPLICABLE", _("不适用")


# ──────────────────────────────────────────────────────────────────────
# 异常目录（总册 §73，code 稳定）
# ──────────────────────────────────────────────────────────────────────
class ExceptionCode(models.TextChoices):
    MISSING_IN = "MISSING_IN", _("缺签到")
    MISSING_OUT = "MISSING_OUT", _("缺签退")
    LATE = "LATE", _("迟到")
    EARLY_OUT = "EARLY_OUT", _("早退")
    INSUFFICIENT_HOURS = "INSUFFICIENT_HOURS", _("工时不足")
    EXCESS_HOURS = "EXCESS_HOURS", _("工时超标")
    OVERLAP_LEAVE = "OVERLAP_LEAVE", _("与请假重叠")
    OVERLAP_SCHEDULE = "OVERLAP_SCHEDULE", _("排班重叠")
    DEVICE_CONFLICT = "DEVICE_CONFLICT", _("设备冲突")
    DUPLICATE_EVENT = "DUPLICATE_EVENT", _("重复事件")
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE", _("未知来源")
    UNAUTHORIZED_LOCATION = "UNAUTHORIZED_LOCATION", _("未授权地点")
    OUT_OF_WINDOW = "OUT_OF_WINDOW", _("超出时段")


# ──────────────────────────────────────────────────────────────────────
# 加班（总册 §77）
# ──────────────────────────────────────────────────────────────────────
class OvertimeSettlementMode(models.TextChoices):
    PAY_CANDIDATE = "PAY_CANDIDATE", _("支付候选")
    COMP_TIME = "COMP_TIME", _("转调休")
    NO_COMPENSATION = "NO_COMPENSATION", _("不补偿")
    POLICY_DEPENDENT = "POLICY_DEPENDENT", _("依政策")


# ──────────────────────────────────────────────────────────────────────
# 假别目录（总册 §83；法律适用由 RulePack 决定）
# ──────────────────────────────────────────────────────────────────────
class LeaveCategory(models.TextChoices):
    ANNUAL = "ANNUAL", _("年休假")
    SICK = "SICK", _("病假")
    PERSONAL = "PERSONAL", _("事假")
    MARRIAGE = "MARRIAGE", _("婚假")
    BEREAVEMENT = "BEREAVEMENT", _("丧假")
    MATERNITY = "MATERNITY", _("产假")
    PATERNITY_OR_CARE = "PATERNITY_OR_CARE", _("陪产/护理假")
    PARENTAL = "PARENTAL", _("育儿假")
    FAMILY_VISIT = "FAMILY_VISIT", _("探亲假")
    WORK_INJURY = "WORK_INJURY", _("工伤停工留薪")
    COMP_TIME = "COMP_TIME", _("调休")
    ACADEMIC_OR_SABBATICAL = "ACADEMIC_OR_SABBATICAL", _("学术/学术休假")
    OTHER = "OTHER", _("其他")


class LeaveUnit(models.TextChoices):
    DAYS = "DAYS", _("天")
    HOURS = "HOURS", _("小时")
    MINUTES = "MINUTES", _("分钟")


class LeaveRequestStatus(models.TextChoices):
    DRAFT = "DRAFT", _("草稿")
    SUBMITTED = "SUBMITTED", _("已提交")
    UNDER_REVIEW = "UNDER_REVIEW", _("审批中")
    APPROVED = "APPROVED", _("已批准")
    SCHEDULED = "SCHEDULED", _("已排程")
    IN_PROGRESS = "IN_PROGRESS", _("进行中")
    COMPLETED = "COMPLETED", _("已完成")
    RETURNED_FROM_LEAVE = "RETURNED_FROM_LEAVE", _("已销假")
    CLOSED = "CLOSED", _("已关闭")
    RETURNED = "RETURNED", _("退回")
    REJECTED = "REJECTED", _("拒绝")
    WITHDRAWN = "WITHDRAWN", _("已撤回")
    CANCELLED = "CANCELLED", _("已取消")
    CHANGE_IN_PROGRESS = "CHANGE_IN_PROGRESS", _("变更中")
    VOID = "VOID", _("作废")


class LeaveLedgerEntryType(models.TextChoices):
    GRANT = "GRANT", _("授予")
    ACCRUAL = "ACCRUAL", _("累积")
    RESERVE = "RESERVE", _("预占")
    RESERVATION_RELEASE = "RESERVATION_RELEASE", _("预占释放")
    USE = "USE", _("使用")
    RESTORE = "RESTORE", _("恢复")
    ADJUST = "ADJUST", _("人工调整")
    CARRY_FORWARD = "CARRY_FORWARD", _("结转")
    EXPIRE = "EXPIRE", _("过期")
    CONVERT = "CONVERT", _("折算")
    MIGRATION = "MIGRATION", _("迁移")


# ──────────────────────────────────────────────────────────────────────
# 月结（总册 §113/§123）
# ──────────────────────────────────────────────────────────────────────
class ClosePeriodStatus(models.TextChoices):
    OPEN = "OPEN", _("开启")
    PRE_CLOSE = "PRE_CLOSE", _("预关闭")
    CLOSED = "CLOSED", _("已关闭")
    REOPENED = "REOPENED", _("已重开")


class TimeRiskCode(models.TextChoices):
    UNEXCUSED_ABSENCE_THRESHOLD = "UNEXCUSED_ABSENCE_THRESHOLD", _("旷工阈值")
    DEVICE_DATA_GAP = "DEVICE_DATA_GAP", _("设备数据缺口")
    LEAVE_LEDGER_DRIFT = "LEAVE_LEDGER_DRIFT", _("假期账户漂移")
    POLICY_AMBIGUITY = "POLICY_AMBIGUITY", _("规则歧义")
    SCHEDULE_GAP = "SCHEDULE_GAP", _("排班缺口")
    CLOSE_OVERDUE = "CLOSE_OVERDUE", _("月结逾期")
    OVERTIME_ANOMALY = "OVERTIME_ANOMALY", _("加班异常")
    MASS_LATE_PATTERN = "MASS_LATE_PATTERN", _("集中迟到模式")
    SOURCE_RECONCILIATION_FAILED = "SOURCE_RECONCILIATION_FAILED", _("数据源对账失败")
