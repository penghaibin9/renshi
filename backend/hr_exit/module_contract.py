"""Machine-readable boundary contract for HR16 exit/retirement cutover."""

MODULE_CODE = "HR16"
MODULE_NAME = "退休与离校"
APP_LABEL = "hr_exit"
AUTHORITY_KIND = "exit_and_retirement_facts"
IMPLEMENTATION_STRATEGY = "rewrite"
CANONICAL_API_PREFIX = "/api/v1/hr/exit"
PERMISSION_PREFIX = "hr.exit"
UPSTREAM_AUTHORITIES = ("HR02", "HR03", "HR07", "HR14", "HR15")
DOWNSTREAM_CONSUMERS = ("HR03", "HR17", "HR18")
LEGACY_TECH_SOURCES = ("offboarding",)
LEGACY_FORMAL_WRITER_ALLOWED = False
OWNS = (
    "离校与退休 Case、规则版本和完成 Gate",
    "ExitFact、RetirementFact、离校交接与关系转移证据",
    "离退休历史、档案转递状态与返聘衔接事实",
    "租户私有离校凭证与不可变下载审计",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 处分决定与人员主档事实",
    "HR15 工资结算和支付事实",
    "legacy offboarding 正式写入",
)
