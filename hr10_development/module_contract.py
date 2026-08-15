"""Machine-readable boundary contract for HR10."""

MODULE_CODE = "HR10"
MODULE_NAME = "培训进修与企业实践"
APP_LABEL = "hr10_development"
AUTHORITY_KIND = "teacher_development"
IMPLEMENTATION_STRATEGY = "new"
CANONICAL_API_PREFIX = "/api/v1/hr/development"
PERMISSION_PREFIX = "hr.development"
UPSTREAM_AUTHORITIES = ("HR03", "HR08", "HR09", "HR11", "HR12")
DOWNSTREAM_CONSUMERS = ("HR09", "HR12", "HR17", "HR18")
OWNS = (
    "教师发展计划及冻结版本",
    "培训进修项目、报名审批、参与与完成核验事实",
    "企业实践项目、过程证据、评价、成果与发展档案",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 学历学位与人员主档事实",
    "HR09 法定资格及双师认定结果",
    "HR15 最终报销、工资与支付事实",
)
