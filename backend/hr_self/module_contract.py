"""Machine-readable boundary contract for HR17 employee self-service."""

MODULE_CODE = "HR17"
MODULE_NAME = "教职工服务"
APP_LABEL = "hr_self"
AUTHORITY_KIND = "self_service_experience"
IMPLEMENTATION_STRATEGY = "rewrite"
CANONICAL_API_PREFIX = "/api/v1/hr/self"
PERMISSION_PREFIX = "hr.self"
UPSTREAM_AUTHORITIES = tuple("HR%02d" % i for i in range(3, 17))
DOWNSTREAM_CONSUMERS = ()
BUSINESS_FACT_AUTHORITY = False
OWNS = (
    "SELF 身份解析、服务目录与统一个人体验",
    "本人聚合视图、业务发起路由、待办与文件访问体验",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03-HR16 任一正式业务事实",
    "跨域状态机副本",
    "薪酬、合同、考核、职称、聘任、离退第二套真值",
)
