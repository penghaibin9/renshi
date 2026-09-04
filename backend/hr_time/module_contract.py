"""HR11 考勤与假期模块边界合同。"""

MODULE_CODE = "HR11"
MODULE_NAME = "考勤与假期"
APP_LABEL = "hr_time"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "考勤规则、排班与日历业务事实",
    "签到、缺勤、异常与受控更正事实",
    "请假、销假、假期额度及其审计事实",
    "租户私有请假证明与不可变下载审计",
)
REQUIRED_GUARDS = (
    "tenant fail-closed",
    "考勤更正必须可审计",
    "时间与有效期事实不得被当前配置反向改写",
    "跨域只走 provider/command/event",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 教职工主档",
    "HR06 人事异动事实",
    "HR12 考核结果",
)
