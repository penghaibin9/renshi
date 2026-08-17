"""HR03 canonical Authority permission/event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_PERSONNEL_DECISION_VIEW = "hr.staff.personnel_decision.view"
PERM_PERSONNEL_DECISION_MANAGE = "hr.staff.personnel_decision.manage"
PERM_REWARD_DISCIPLINARY_VIEW = "hr.staff.reward_disciplinary.view"
PERM_REWARD_DISCIPLINARY_MANAGE = "hr.staff.reward_disciplinary.manage"

PERMISSION_DEFINITIONS = (
    PermissionDefinition(
        PERM_PERSONNEL_DECISION_VIEW, "HR03", "查看正式人事决定事实"
    ),
    PermissionDefinition(
        PERM_PERSONNEL_DECISION_MANAGE, "HR03", "签发/更正/撤销正式人事决定"
    ),
    PermissionDefinition(
        PERM_REWARD_DISCIPLINARY_VIEW, "HR03", "查看奖惩/处分案例与正式事实"
    ),
    PermissionDefinition(
        PERM_REWARD_DISCIPLINARY_MANAGE, "HR03", "办理奖惩/处分并形成正式决定"
    ),
)
register_permissions(PERMISSION_DEFINITIONS)

EVENT_PERSONNEL_DECISION_EFFECTIVE = "hr.staff.personnel_decision.effective"
EVENT_REWARD_DISCIPLINARY_EFFECTIVE = "hr.staff.reward_disciplinary.effective"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(
        EVENT_PERSONNEL_DECISION_EFFECTIVE,
        "HR03",
        "personnel_decision",
        1,
        "不可变人事决定事实生效",
    ),
    BusinessEventDefinition(
        EVENT_REWARD_DISCIPLINARY_EFFECTIVE,
        "HR03",
        "reward_disciplinary",
        1,
        "奖惩/处分案例形成正式生效事实",
    ),
)
register_business_events(EVENT_DEFINITIONS)
