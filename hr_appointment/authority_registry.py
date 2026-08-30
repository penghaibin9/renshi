"""HR14 canonical permissions and versioned public business events."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from .permissions import (
    APPLICATION_PERMISSION,
    EFFECT_PERMISSION,
    MANAGE_PERMISSION,
    PUBLICITY_PERMISSION,
    READ_PERMISSION,
    REVIEW_PERMISSION,
)

PERM_TERM = "hr.appointment.term"
PERM_DECISION = "hr.appointment.decision"

register_permissions(
    (
        PermissionDefinition(READ_PERMISSION, "HR14", "查看岗位聘任工作区"),
        PermissionDefinition(APPLICATION_PERMISSION, "HR14", "办理岗位竞聘申报"),
        PermissionDefinition(MANAGE_PERMISSION, "HR14", "管理竞聘批次和资格审查"),
        PermissionDefinition(REVIEW_PERMISSION, "HR14", "执行评审和最终排名"),
        PermissionDefinition(PUBLICITY_PERMISSION, "HR14", "办理拟聘公示和异议"),
        PermissionDefinition(PERM_DECISION, "HR14", "记录集体决策事实"),
        PermissionDefinition(EFFECT_PERMISSION, "HR14", "发起并确认聘任生效"),
        PermissionDefinition(PERM_TERM, "HR14", "办理任期、续聘、调整和终止"),
    )
)

EVENT_DECISION_APPROVED = "hr.appointment.decision.approved"
EVENT_FACT_EFFECTIVE = "hr.appointment.fact.effective"
EVENT_TERM_EFFECTIVE = "hr.appointment.term.effective"

register_business_events(
    (
        BusinessEventDefinition(
            EVENT_DECISION_APPROVED,
            "HR14",
            "decision",
            1,
            "集体决策形成不可变通过事实",
        ),
        BusinessEventDefinition(
            EVENT_FACT_EFFECTIVE,
            "HR14",
            "fact",
            1,
            "HR03 回执确认岗位聘任正式生效",
        ),
        BusinessEventDefinition(
            EVENT_TERM_EFFECTIVE,
            "HR14",
            "term",
            1,
            "岗位聘任任期正式生效或追加新版本",
        ),
    )
)
