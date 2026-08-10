"""HR09 资质与双师模块边界合同。"""

MODULE_CODE = "HR09"
MODULE_NAME = "资质与双师认定"
APP_LABEL = "hr_qualification"
CANONICAL_API_ROOT = "/api/v1/hr"

OWNS = (
    "教师资质与证书事实",
    "双师认定案例、认定结果及有效期",
    "资质核验、到期和复核事实",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 教职工主档",
    "HR10 培训进修事实",
    "HR12 考核结果",
)
REQUIRED_GUARDS = (
    "tenant fail-closed",
    "证书/认定有效期历史",
    "跨域只走 provider/command/event",
)
