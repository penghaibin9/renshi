"""HR15 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_BENEFIT_VIEW = "hr.payroll.benefit.view"
PERM_BENEFIT_MANAGE = "hr.payroll.benefit.manage"
PERM_PENSION_VIEW = "hr.payroll.pension.view"
PERM_PENSION_MANAGE = "hr.payroll.pension.manage"
PERM_PENSION_CLOSE = "hr.payroll.pension.close"
PERM_RULE_MANAGE = "hr.payroll.rule.manage"
PERM_INPUT_MANAGE = "hr.payroll.input.manage"
PERM_CALCULATE = "hr.payroll.calculate"
PERM_REVIEW = "hr.payroll.review"
PERM_FINALIZE = "hr.payroll.finalize"
PERM_PAYMENT = "hr.payroll.payment"
PERM_PAYSLIP_SENSITIVE = "hr.payroll.payslip.view_sensitive"
PERM_RECONCILE = "hr.payroll.reconcile"
PERM_STATUTORY_VIEW = "hr.payroll.statutory.view"
PERM_STATUTORY_MANAGE = "hr.payroll.statutory.manage"
PERM_LEGACY_TAKEOVER_VIEW = "hr.payroll.legacy_takeover.view"
PERM_LEGACY_TAKEOVER_MANAGE = "hr.payroll.legacy_takeover.manage"
register_permissions((
    PermissionDefinition(PERM_BENEFIT_VIEW, "HR15", "查看福利计划及个人福利事实"),
    PermissionDefinition(PERM_BENEFIT_MANAGE, "HR15", "管理福利制度与个人福利事实"),
    PermissionDefinition(PERM_PENSION_VIEW, "HR15", "查看职业年金计划、缴费与结算"),
    PermissionDefinition(PERM_PENSION_MANAGE, "HR15", "管理职业年金计划与缴费事实"),
    PermissionDefinition(PERM_PENSION_CLOSE, "HR15", "关闭职业年金期间并生成结算事实"),
    PermissionDefinition(PERM_RULE_MANAGE, "HR15", "管理薪资项目和规则版本"),
    PermissionDefinition(PERM_INPUT_MANAGE, "HR15", "冻结版本化薪酬输入快照"),
    PermissionDefinition(PERM_CALCULATE, "HR15", "执行可解释薪酬计算"),
    PermissionDefinition(PERM_REVIEW, "HR15", "复核薪酬计算结果"),
    PermissionDefinition(PERM_FINALIZE, "HR15", "封板已复核薪酬结果"),
    PermissionDefinition(PERM_PAYMENT, "HR15", "签发支付指令并接收回执"),
    PermissionDefinition(PERM_PAYSLIP_SENSITIVE, "HR15", "查看高敏工资条"),
    PermissionDefinition(PERM_RECONCILE, "HR15", "执行银行及财务对账"),
    PermissionDefinition(PERM_STATUTORY_VIEW, "HR15", "查看社保及住房公积金规则与缴费事实"),
    PermissionDefinition(PERM_STATUTORY_MANAGE, "HR15", "管理社保及住房公积金版本化规则"),
    PermissionDefinition(PERM_LEGACY_TAKEOVER_VIEW, "HR15", "查看旧薪资接管清单、映射与切换证据"),
    PermissionDefinition(PERM_LEGACY_TAKEOVER_MANAGE, "HR15", "盘点、核验并激活旧薪资只读接管"),
))

EVENT_BENEFIT_PLAN_PUBLISHED = "hr.payroll.benefit_plan.published"
EVENT_BENEFIT_ENROLLMENT_EFFECTIVE = "hr.payroll.benefit_enrollment.effective"
EVENT_PENSION_PLAN_PUBLISHED = "hr.payroll.pension_plan.published"
EVENT_PENSION_CONTRIBUTION_FINALIZED = "hr.payroll.pension_contribution.finalized"
EVENT_PENSION_SETTLEMENT_CLOSED = "hr.payroll.pension_settlement.closed"
EVENT_CALCULATION_COMPLETED = "hr.payroll.calculation.completed"
EVENT_REVIEW_COMPLETED = "hr.payroll.review.completed"
EVENT_PERIOD_FINALIZED = "hr.payroll.period.finalized"
EVENT_PAYMENT_ACCEPTED = "hr.payroll.payment.accepted"
EVENT_PAYSLIP_PUBLISHED = "hr.payroll.payslip.published"
EVENT_FINANCE_RECONCILED = "hr.payroll.finance.reconciled"
EVENT_STATUTORY_RULE_PUBLISHED = "hr.payroll.statutory_rule.published"
EVENT_STATUTORY_CONTRIBUTION_CALCULATED = "hr.payroll.statutory_contribution.calculated"
EVENT_STATUTORY_CONTRIBUTION_REVIEWED = "hr.payroll.statutory_contribution.reviewed"
EVENT_STATUTORY_CONTRIBUTION_SEALED = "hr.payroll.statutory_contribution.sealed"
EVENT_LEGACY_INVENTORY_CAPTURED = "hr.payroll.legacy_inventory.captured"
EVENT_LEGACY_CUTOVER_ACTIVATED = "hr.payroll.legacy_cutover.activated"
register_business_events((
    BusinessEventDefinition(EVENT_BENEFIT_PLAN_PUBLISHED, "HR15", "benefit_plan", 1),
    BusinessEventDefinition(EVENT_BENEFIT_ENROLLMENT_EFFECTIVE, "HR15", "benefit_enrollment", 1),
    BusinessEventDefinition(EVENT_PENSION_PLAN_PUBLISHED, "HR15", "pension_plan", 1),
    BusinessEventDefinition(EVENT_PENSION_CONTRIBUTION_FINALIZED, "HR15", "pension_contribution", 1),
    BusinessEventDefinition(EVENT_PENSION_SETTLEMENT_CLOSED, "HR15", "pension_settlement", 1),
    BusinessEventDefinition(EVENT_CALCULATION_COMPLETED, "HR15", "calculation", 1),
    BusinessEventDefinition(EVENT_REVIEW_COMPLETED, "HR15", "review", 1),
    BusinessEventDefinition(EVENT_PERIOD_FINALIZED, "HR15", "period", 1),
    BusinessEventDefinition(EVENT_PAYMENT_ACCEPTED, "HR15", "payment", 1),
    BusinessEventDefinition(EVENT_PAYSLIP_PUBLISHED, "HR15", "payslip", 1),
    BusinessEventDefinition(EVENT_FINANCE_RECONCILED, "HR15", "finance", 1),
    BusinessEventDefinition(EVENT_STATUTORY_RULE_PUBLISHED, "HR15", "statutory_rule", 1),
    BusinessEventDefinition(EVENT_STATUTORY_CONTRIBUTION_CALCULATED, "HR15", "statutory_contribution", 1),
    BusinessEventDefinition(EVENT_STATUTORY_CONTRIBUTION_REVIEWED, "HR15", "statutory_contribution", 1),
    BusinessEventDefinition(EVENT_STATUTORY_CONTRIBUTION_SEALED, "HR15", "statutory_contribution", 1),
    BusinessEventDefinition(EVENT_LEGACY_INVENTORY_CAPTURED, "HR15", "legacy_inventory", 1),
    BusinessEventDefinition(EVENT_LEGACY_CUTOVER_ACTIVATED, "HR15", "legacy_cutover", 1),
))
