"""HR06 人事异动模块边界合同。"""

MODULE_CODE = "HR06"
MODULE_NAME = "人事异动"
APP_LABEL = "hr_changes"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "调动、转岗、离岗等人事异动案例",
    "异动审批与生效事实",
    "异动命令、幂等执行与审计记录",
)
REQUIRED_GUARDS = (
    "Person Transition Lock",
    "tenant fail-closed",
    "幂等键",
    "Outbox/Inbox 可靠事件",
    "FINAL/EFFECTIVE/CLOSED 不可变",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR02 组织岗位权威事实",
    "HR03 教职工主档权威事实",
    "HR07 合同权威事实",
)
