"""Machine-readable boundary contract for HR18 data/reporting governance."""

MODULE_CODE = "HR18"
MODULE_NAME = "人事数据中心"
APP_LABEL = "hr_data"
AUTHORITY_KIND = "data_governance_and_formal_submission"
IMPLEMENTATION_STRATEGY = "rewrite"
CANONICAL_API_PREFIX = "/api/v1/hr/data"
PERMISSION_PREFIX = "hr.data"
UPSTREAM_AUTHORITIES = tuple("HR%02d" % i for i in range(1, 18))
DOWNSTREAM_CONSUMERS = ()
LEGACY_TECH_SOURCES = ("report",)
LEGACY_FORMAL_WRITER_ALLOWED = False
BUSINESS_FACT_BACKWRITE_ALLOWED = False
OWNS = (
    "指标、报表、数据集、质量、血缘与交换定义",
    "正式报送定义、冻结快照、审批、回执、更正与档案",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR02-HR17 正式业务事实",
    "第二份可编辑 Staff/Contract/Payroll/Exit 事实",
    "legacy report 正式写入",
)
