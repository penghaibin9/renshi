"""HR13 canonical permissions and versioned public business events."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_VIEW = "hr.title.view"
PERM_REVIEW = "hr.title.review"
PERM_PANEL = "hr.title.panel"
PERM_PUBLICITY = "hr.title.publicity"
PERM_RESULT = "hr.title.result"
PERM_RESULT_CORRECT = "hr.title.result.correct"

register_permissions(
    (
        PermissionDefinition(PERM_VIEW, "HR13", "查看职称评审工作区"),
        PermissionDefinition(PERM_REVIEW, "HR13", "执行资格审查"),
        PermissionDefinition(PERM_PANEL, "HR13", "维护专家分配和匿名票决"),
        PermissionDefinition(PERM_PUBLICITY, "HR13", "办理公示和异议复核"),
        PermissionDefinition(PERM_RESULT, "HR13", "发布首次正式职称结果"),
        PermissionDefinition(
            PERM_RESULT_CORRECT,
            "HR13",
            "修订和撤销已封板的正式职称结果",
        ),
    )
)

EVENT_RESULT_PUBLISHED = "hr.title.result.published"
EVENT_RESULT_REVISED = "hr.title.result.revised"
EVENT_RESULT_REVOKED = "hr.title.result.revoked"

register_business_events(
    (
        BusinessEventDefinition(
            EVENT_RESULT_PUBLISHED,
            "HR13",
            "result",
            1,
            "不可变正式职称结果首次发布",
        ),
        BusinessEventDefinition(
            EVENT_RESULT_REVISED,
            "HR13",
            "result",
            1,
            "通过追加版本修订正式职称结果",
        ),
        BusinessEventDefinition(
            EVENT_RESULT_REVOKED,
            "HR13",
            "result",
            1,
            "通过追加撤销事实终止正式职称结果",
        ),
    )
)
