"""
hr_time/constants.py

HR11 冻结常量：错误码（总册 §139）、权限码（§151）、数据范围（§152）、
SoD 风险对（§153）、数据保留分层（§182）。

这些是契约常量，不是 Python 行为判断——假别规则、宽限、加班资格等
一律走版本化规则，禁止在此硬编码 `if leave_type == ...`。
"""

from django.utils.translation import gettext_lazy as _

# ──────────────────────────────────────────────────────────────────────
# API 版本（总册 §130）
# ──────────────────────────────────────────────────────────────────────
API_VERSION = "1"
SCHEMA_VERSION = "1.0"


# ──────────────────────────────────────────────────────────────────────
# 错误码（总册 §139 冻结清单）
# ──────────────────────────────────────────────────────────────────────
class TimeErrorCode:
    # 通用/租户
    TENANT_CONTEXT_REQUIRED = "TENANT_CONTEXT_REQUIRED"
    TENANT_SCOPE_VIOLATION = "TENANT_SCOPE_VIOLATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_REQUEST = "INVALID_REQUEST"
    VERSION_CONFLICT = "VERSION_CONFLICT"

    # 政策/日历/排班
    TIME_POLICY_NOT_FOUND = "TIME_POLICY_NOT_FOUND"
    TIME_POLICY_AMBIGUOUS = "TIME_POLICY_AMBIGUOUS"
    TIME_POLICY_VERSION_STALE = "TIME_POLICY_VERSION_STALE"
    CALENDAR_VERSION_NOT_FOUND = "CALENDAR_VERSION_NOT_FOUND"
    SCHEDULE_NOT_FOUND = "SCHEDULE_NOT_FOUND"
    SCHEDULE_OVERLAP = "SCHEDULE_OVERLAP"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"

    # 事件/打卡
    TIME_EVENT_DUPLICATE = "TIME_EVENT_DUPLICATE"
    TIME_EVENT_SOURCE_INVALID = "TIME_EVENT_SOURCE_INVALID"
    TIME_EVENT_SIGNATURE_INVALID = "TIME_EVENT_SIGNATURE_INVALID"
    TIME_EVENT_PERSON_UNMAPPED = "TIME_EVENT_PERSON_UNMAPPED"
    TIME_EVENT_PAIR_AMBIGUOUS = "TIME_EVENT_PAIR_AMBIGUOUS"
    TIME_EVENT_OUT_OF_WINDOW = "TIME_EVENT_OUT_OF_WINDOW"

    # 考勤/更正/加班
    ATTENDANCE_FACT_CONFLICT = "ATTENDANCE_FACT_CONFLICT"
    ATTENDANCE_PERIOD_CLOSED = "ATTENDANCE_PERIOD_CLOSED"
    CORRECTION_NOT_ALLOWED = "CORRECTION_NOT_ALLOWED"
    OVERTIME_NOT_ELIGIBLE = "OVERTIME_NOT_ELIGIBLE"
    OVERTIME_WINDOW_CONFLICT = "OVERTIME_WINDOW_CONFLICT"

    # 请假
    LEAVE_POLICY_NOT_FOUND = "LEAVE_POLICY_NOT_FOUND"
    LEAVE_NOT_ELIGIBLE = "LEAVE_NOT_ELIGIBLE"
    LEAVE_BALANCE_INSUFFICIENT = "LEAVE_BALANCE_INSUFFICIENT"
    LEAVE_BALANCE_CONFLICT = "LEAVE_BALANCE_CONFLICT"
    LEAVE_OVERLAP = "LEAVE_OVERLAP"
    LEAVE_EVIDENCE_REQUIRED = "LEAVE_EVIDENCE_REQUIRED"
    LEAVE_ALREADY_APPROVED = "LEAVE_ALREADY_APPROVED"
    LEAVE_ALREADY_STARTED = "LEAVE_ALREADY_STARTED"
    LEAVE_CHANGE_REQUIRES_REVIEW = "LEAVE_CHANGE_REQUIRES_REVIEW"
    LEAVE_LEDGER_DRIFT = "LEAVE_LEDGER_DRIFT"

    # 月结/数据源
    TIME_CLOSE_BLOCKED = "TIME_CLOSE_BLOCKED"
    TIME_SOURCE_UNAVAILABLE = "TIME_SOURCE_UNAVAILABLE"


# 总册 §139 全量清单（用于文档/校验）
ALL_TIME_ERROR_CODES = frozenset(
    code for code in vars(TimeErrorCode).values() if isinstance(code, str)
)


# ──────────────────────────────────────────────────────────────────────
# 权限码（总册 §151：权限 = action + data scope + object lifecycle + field/file policy）
# ──────────────────────────────────────────────────────────────────────
class TimePermissionCode:
    HR11_TIME_ADMIN = "hr.time.admin"  # 时间域总管理员
    HR11_POLICY_MANAGER = "hr.time.policy.manage"  # 规则包/版本管理
    HR11_SCHEDULE_MANAGER = "hr.time.schedule.manage"  # 日历/班次/排班管理
    HR11_ATTENDANCE_MANAGER = "hr.time.attendance.manage"  # 考勤事实管理
    HR11_ATTENDANCE_VERIFIER = "hr.time.attendance.verify"  # 考勤核验
    HR11_LEAVE_ADMIN = "hr.time.leave.admin"  # 请假管理（账户/调整）
    HR11_LEAVE_APPROVER = "hr.time.leave.approve"  # 请假审批
    HR11_OVERTIME_APPROVER = "hr.time.overtime.approve"  # 加班审批
    HR11_PERIOD_CLOSER = "hr.time.close"  # 月结关闭
    HR11_PERIOD_REOPEN_REQUESTER = "hr.time.close.reopen_request"  # 申请重开
    HR11_PERIOD_REOPEN_APPROVER = "hr.time.close.reopen_approve"  # 独立审批重开
    HR11_AUDITOR = "hr.time.audit"  # 审计只读
    HR11_EMPLOYEE_SELF = "hr.time.self"  # 员工自助
    HR11_MANAGER_TEAM = "hr.time.team.view"  # 主管团队视图
    HR11_DEVICE_ADMIN = "hr.time.device.admin"  # 设备管理
    HR11_READ_ANALYTICS = "hr.time.analytics.read"  # 只读统计


ALL_TIME_PERMISSIONS = tuple(
    (code, verbose)
    for code, verbose in [
        (TimePermissionCode.HR11_TIME_ADMIN, _("HR Time: Admin")),
        (TimePermissionCode.HR11_POLICY_MANAGER, _("HR Time: Policy Manager")),
        (TimePermissionCode.HR11_SCHEDULE_MANAGER, _("HR Time: Schedule Manager")),
        (TimePermissionCode.HR11_ATTENDANCE_MANAGER, _("HR Time: Attendance Manager")),
        (TimePermissionCode.HR11_ATTENDANCE_VERIFIER, _("HR Time: Attendance Verifier")),
        (TimePermissionCode.HR11_LEAVE_ADMIN, _("HR Time: Leave Admin")),
        (TimePermissionCode.HR11_LEAVE_APPROVER, _("HR Time: Leave Approver")),
        (TimePermissionCode.HR11_OVERTIME_APPROVER, _("HR Time: Overtime Approver")),
        (TimePermissionCode.HR11_PERIOD_CLOSER, _("HR Time: Period Closer")),
        (TimePermissionCode.HR11_PERIOD_REOPEN_REQUESTER, _("HR Time: Reopen Requester")),
        (TimePermissionCode.HR11_PERIOD_REOPEN_APPROVER, _("HR Time: Reopen Approver")),
        (TimePermissionCode.HR11_AUDITOR, _("HR Time: Auditor")),
        (TimePermissionCode.HR11_EMPLOYEE_SELF, _("HR Time: Employee Self Service")),
        (TimePermissionCode.HR11_MANAGER_TEAM, _("HR Time: Manager Team")),
        (TimePermissionCode.HR11_DEVICE_ADMIN, _("HR Time: Device Admin")),
        (TimePermissionCode.HR11_READ_ANALYTICS, _("HR Time: Read Analytics")),
    ]
)


# ──────────────────────────────────────────────────────────────────────
# 数据范围（总册 §152：跨校永不自动开放）
# ──────────────────────────────────────────────────────────────────────
class TimeDataScope:
    SELF = "SELF"
    DIRECT_REPORTS = "DIRECT_REPORTS"
    ORG_SUBTREE = "ORG_SUBTREE"
    ASSIGNED_ORGS = "ASSIGNED_ORGS"
    LOCATION = "LOCATION"
    TENANT_ALL = "TENANT_ALL"
    AUDIT_READONLY = "AUDIT_READONLY"


ALL_TIME_DATA_SCOPES = frozenset(
    {
        TimeDataScope.SELF,
        TimeDataScope.DIRECT_REPORTS,
        TimeDataScope.ORG_SUBTREE,
        TimeDataScope.ASSIGNED_ORGS,
        TimeDataScope.LOCATION,
        TimeDataScope.TENANT_ALL,
        TimeDataScope.AUDIT_READONLY,
    }
)


# ──────────────────────────────────────────────────────────────────────
# 职责分离（总册 §153）：高风险 SoD 对
# ──────────────────────────────────────────────────────────────────────
# (角色 A, 角色 B) 不可由同一账号同时执行
TIME_SEPARATION_OF_DUTIES = frozenset(
    {
        ("policy.manage", "audit"),  # 规则发布人与最终审计分离
        ("attendance.manage", "attendance.verify"),  # 补卡更正与核验分离
        ("leave.admin", "leave.approve"),  # 手工调余额与审批分离
        ("close", "attendance.manage"),  # 月结关闭不能静默改事实
        ("device.admin", "attendance.manage"),  # 设备管理员不自动具备人员考勤更正权
    }
)
