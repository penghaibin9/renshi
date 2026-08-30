"""HR14 canonical permissions and versioned public business events."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from .permissions import (
    APPLICATION_PERMISSION,
    EFFECT_PERMISSION,
    FACT_CORRECT_PERMISSION,
    FACT_PUBLISH_PERMISSION,
    FACT_REVOKE_PERMISSION,
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
        PermissionDefinition(FACT_PUBLISH_PERMISSION, "HR14", "首次发布正式任命事实"),
        PermissionDefinition(FACT_CORRECT_PERMISSION, "HR14", "追加正式任命更正事实"),
        PermissionDefinition(FACT_REVOKE_PERMISSION, "HR14", "追加正式任命撤销事实"),
        PermissionDefinition(PERM_TERM, "HR14", "办理任期、续聘、调整和终止"),
    )
)

EVENT_DECISION_APPROVED = "hr.appointment.decision.approved"
EVENT_RANKING_PUBLISHED = "hr.appointment.ranking.published"
EVENT_FACT_EFFECTIVE = "hr.appointment.fact.effective"
EVENT_FACT_CORRECTED = "hr.appointment.fact.corrected"
EVENT_FACT_REVOKED = "hr.appointment.fact.revoked"
EVENT_FACT_ENDED = "hr.appointment.fact.ended"
EVENT_TERM_EFFECTIVE = "hr.appointment.term.effective"

register_business_events(
    (
        BusinessEventDefinition(
            EVENT_RANKING_PUBLISHED,
            "HR14",
            "ranking",
            1,
            "服务端依据封板评价事实发布最终排名",
        ),
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
            EVENT_FACT_CORRECTED,
            "HR14",
            "fact",
            1,
            "授权更正以追加事实版本封存",
        ),
        BusinessEventDefinition(
            EVENT_FACT_REVOKED,
            "HR14",
            "fact",
            1,
            "授权撤销以追加事实版本封存",
        ),
        BusinessEventDefinition(
            EVENT_FACT_ENDED,
            "HR14",
            "fact",
            1,
            "离退或聘期治理以追加事实版本封存",
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
