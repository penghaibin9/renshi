"""HR02 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_structure.permissions import HR02_PERMISSIONS


PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(code, "HR02", code.replace("hr.", "").replace(".", " "))
    for code in HR02_PERMISSIONS
)
register_permissions(PERMISSION_DEFINITIONS)

EVENT_ORGANIZATION_CREATED = "hr.structure.organization.created"
EVENT_ORGANIZATION_CHANGED = "hr.structure.organization.changed"
EVENT_POSITION_CREATED = "hr.structure.position.created"
EVENT_POSITION_STATUS_CHANGED = "hr.structure.position.status_changed"
EVENT_RESERVATION_HELD = "hr.structure.reservation.held"
EVENT_RESERVATION_COMMITTED = "hr.structure.reservation.committed"
EVENT_RESERVATION_RELEASED = "hr.structure.reservation.released"
EVENT_STAFFING_PLAN_APPROVED = "hr.structure.staffing_plan.approved"
EVENT_REORGANIZATION_EFFECTIVE = "hr.structure.reorganization.effective"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_ORGANIZATION_CREATED, "HR02", "organization", 1),
    BusinessEventDefinition(EVENT_ORGANIZATION_CHANGED, "HR02", "organization", 1),
    BusinessEventDefinition(EVENT_POSITION_CREATED, "HR02", "position", 1),
    BusinessEventDefinition(EVENT_POSITION_STATUS_CHANGED, "HR02", "position", 1),
    BusinessEventDefinition(EVENT_RESERVATION_HELD, "HR02", "reservation", 1),
    BusinessEventDefinition(EVENT_RESERVATION_COMMITTED, "HR02", "reservation", 1),
    BusinessEventDefinition(EVENT_RESERVATION_RELEASED, "HR02", "reservation", 1),
    BusinessEventDefinition(EVENT_STAFFING_PLAN_APPROVED, "HR02", "staffing_plan", 1),
    BusinessEventDefinition(EVENT_REORGANIZATION_EFFECTIVE, "HR02", "reorganization", 1),
)
register_business_events(EVENT_DEFINITIONS)
