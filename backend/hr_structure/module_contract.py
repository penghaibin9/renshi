"""HR02 组织与岗位模块边界合同。"""

MODULE_CODE = "HR02"
MODULE_NAME = "组织与岗位"
APP_LABEL = "hr_structure"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "组织单元及其有效期历史",
    "岗位及岗位编制事实",
    "组织岗位关系与历史快照",
)
FORBIDDEN_DIRECT_WRITES = (
    "教职工主档",
    "招聘录用结果",
    "合同与人事异动事实",
)

BUSINESS_EVENT_PRODUCER = True
BUSINESS_EVENT_POLICY = "TRANSACTIONAL_OUTBOX"
