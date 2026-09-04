"""HR12 考核与绩效模块边界合同。"""

MODULE_CODE = "HR12"
MODULE_NAME = "考核与绩效"
APP_LABEL = "hr_assessment"
CANONICAL_API_ROOT = "/api/v1/hr"

OWNS = (
    "考核政策、周期与冻结快照",
    "考核对象、目标、证据、评议与校准案例",
    "最终考核结果、通知、异议、修订和归档事实",
    "租户私有审定纪要与不可变下载审计",
)
REQUIRED_GUARDS = (
    "tenant fail-closed",
    "发布/冻结快照不得被当前配置反向改写",
    "命名数据库约束必须稳定",
    "FINAL/EFFECTIVE/CLOSED 不可变",
    "RETURN 与 REJECT 语义分离",
    "signals 仅用于启动期生命周期挂钩，不注册 URL",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 教职工主档",
    "HR09 资质认定事实",
    "HR10 教师发展事实",
    "HR11 考勤事实",
)
STABLE_NAMED_CONSTRAINTS = (
    "uniq_cycle_tenant_no_type",
    "uniq_goal_tenant_code",
    "uniq_reviewer_case_role",
)
