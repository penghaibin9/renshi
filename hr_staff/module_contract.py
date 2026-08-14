"""HR03 教职工主档模块边界合同。"""

MODULE_CODE = "HR03"
MODULE_NAME = "教职工主档"
APP_LABEL = "hr_staff"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "教职工身份主档",
    "教职工基础信息及受控更正历史",
    "人员主标识与在校人事身份事实",
)
FORBIDDEN_DIRECT_WRITES = (
    "组织岗位结构",
    "招聘过程事实",
    "合同与异动历史",
    "考勤考核事实",
)
