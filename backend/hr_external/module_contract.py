"""HR08 外聘/外部人员模块边界合同。"""

MODULE_CODE = "HR08"
MODULE_NAME = "外聘与外部人员"
APP_LABEL = "hr_external"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "外聘与外部人员业务身份",
    "外部用工/聘用案例与有效期",
    "外部人员业务过程与合规材料",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 正式教职工主档",
    "HR07 正式合同权威事实",
    "HR11 考勤权威事实",
)
REQUIRED_GUARDS = (
    "tenant fail-closed",
    "跨域只走 provider/command/event",
    "有效期历史 [effective_from, effective_to)",
)
