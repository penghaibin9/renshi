"""HR10 教师发展模块边界合同。"""

MODULE_CODE = "HR10"
MODULE_NAME = "教师发展与培训进修"
APP_LABEL = "hr10_development"
CANONICAL_API_ROOT = "/api/v1/hr"

OWNS = (
    "教师发展计划与需求",
    "培训、进修、企业实践过程事实",
    "学习参与、完成、成果与发展指标事实",
    "旧系统发展数据暂存与受控迁移事实",
)
REQUIRED_GUARDS = (
    "tenant fail-closed",
    "旧数据 staging 先核验后升级",
    "staging/import 模型必须保持 Django 注册，禁止误删表",
    "Outbox/Inbox 与幂等交接",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 教职工主档",
    "HR09 资质认定结果",
    "HR12 考核结果",
)
