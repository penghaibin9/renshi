"""HR01 模块边界合同。

这是给开发者和测试共同读取的稳定元数据，不在这里放业务逻辑。
"""

MODULE_CODE = "HR01"
MODULE_NAME = "人事控制中心"
APP_LABEL = "hr_control_center"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

# HR01 只负责跨域汇总、工作台投影和治理告警，不成为其他人事事实的第二权威。
OWNS = (
    "跨域工作台投影",
    "治理与运营告警",
    "面向管理者的汇总视图",
)
FORBIDDEN_DIRECT_WRITES = (
    "组织岗位权威事实",
    "教职工主档权威事实",
    "招聘入职合同异动等其他域权威事实",
)
