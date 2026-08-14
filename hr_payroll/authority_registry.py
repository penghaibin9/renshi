"""HR15 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_BENEFIT_VIEW = "hr.payroll.benefit.view"
PERM_BENEFIT_MANAGE = "hr.payroll.benefit.manage"
PERM_PENSION_VIEW = "hr.payroll.pension.view"
PERM_PENSION_MANAGE = "hr.payroll.pension.manage"
PERM_PENSION_CLOSE = "hr.payroll.pension.close"
register_permissions((
    PermissionDefinition(PERM_BENEFIT_VIEW, "HR15", "查看福利计划及个人福利事实"),
    PermissionDefinition(PERM_BENEFIT_MANAGE, "HR15", "管理福利制度与个人福利事实"),
    PermissionDefinition(PERM_PENSION_VIEW, "HR15", "查看职业年金计划、缴费与结算"),
    PermissionDefinition(PERM_PENSION_MANAGE, "HR15", "管理职业年金计划与缴费事实"),
    PermissionDefinition(PERM_PENSION_CLOSE, "HR15", "关闭职业年金期间并生成结算事实"),
))

EVENT_BENEFIT_PLAN_PUBLISHED = "hr.payroll.benefit_plan.published"
EVENT_BENEFIT_ENROLLMENT_EFFECTIVE = "hr.payroll.benefit_enrollment.effective"
EVENT_PENSION_PLAN_PUBLISHED = "hr.payroll.pension_plan.published"
EVENT_PENSION_CONTRIBUTION_FINALIZED = "hr.payroll.pension_contribution.finalized"
EVENT_PENSION_SETTLEMENT_CLOSED = "hr.payroll.pension_settlement.closed"
register_business_events((
    BusinessEventDefinition(EVENT_BENEFIT_PLAN_PUBLISHED, "HR15", "benefit_plan", 1),
    BusinessEventDefinition(EVENT_BENEFIT_ENROLLMENT_EFFECTIVE, "HR15", "benefit_enrollment", 1),
    BusinessEventDefinition(EVENT_PENSION_PLAN_PUBLISHED, "HR15", "pension_plan", 1),
    BusinessEventDefinition(EVENT_PENSION_CONTRIBUTION_FINALIZED, "HR15", "pension_contribution", 1),
    BusinessEventDefinition(EVENT_PENSION_SETTLEMENT_CLOSED, "HR15", "pension_settlement", 1),
))
