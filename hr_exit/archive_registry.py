"""HR16 archive-transfer permission and event definitions."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_ARCHIVE_VIEW = "hr.exit.archive_transfer.view"
PERM_ARCHIVE_MANAGE = "hr.exit.archive_transfer.manage"

register_permissions(
    (
        PermissionDefinition(PERM_ARCHIVE_VIEW, "HR16", "查看档案转递及签收凭证"),
        PermissionDefinition(PERM_ARCHIVE_MANAGE, "HR16", "办理档案转递、签收、退回与更正"),
    )
)

EVENT_ARCHIVE_SENT = "hr.exit.archive_transfer.sent"
EVENT_ARCHIVE_RECEIVED = "hr.exit.archive_transfer.received"
EVENT_ARCHIVE_RETURNED = "hr.exit.archive_transfer.returned"

register_business_events(
    (
        BusinessEventDefinition(EVENT_ARCHIVE_SENT, "HR16", "archive_transfer", 1),
        BusinessEventDefinition(EVENT_ARCHIVE_RECEIVED, "HR16", "archive_transfer", 1),
        BusinessEventDefinition(EVENT_ARCHIVE_RETURNED, "HR16", "archive_transfer", 1),
    )
)
