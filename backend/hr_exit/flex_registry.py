from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions
PERM_FLEX_REVIEW = "hr.exit.flex.review"
register_permissions((PermissionDefinition(PERM_FLEX_REVIEW, "HR16", "核验审批弹性退休（不得本人审批本人）"),))
register_business_events((BusinessEventDefinition("hr.exit.flex.changed", "HR16", "flex", 1),))
