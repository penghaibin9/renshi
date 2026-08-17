"""Machine-readable boundary contract for HR15 payroll cutover."""

MODULE_CODE = "HR15"
MODULE_NAME = "薪酬福利"
APP_LABEL = "hr_payroll"
AUTHORITY_KIND = "payroll_and_benefit_facts"
IMPLEMENTATION_STRATEGY = "rewrite"
CANONICAL_API_PREFIX = "/api/v1/hr/payroll"
PERMISSION_PREFIX = "hr.payroll"
UPSTREAM_AUTHORITIES = ("HR03", "HR05", "HR07", "HR11", "HR12", "HR14", "HR16")
DOWNSTREAM_CONSUMERS = ("HR17", "HR18")
LEGACY_TECH_SOURCES = ("payroll",)
LEGACY_FORMAL_WRITER_ALLOWED = False
OWNS = (
    "薪酬档案、薪资项目与规则版本",
    "月度工资输入快照、计算结果、月结与追溯差额事实",
    "社保公积金、个税、工资条、支付批次与财务对账事实",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 人员与任职事实",
    "HR14 岗位聘任事实",
    "legacy payroll 正式写入",
)
