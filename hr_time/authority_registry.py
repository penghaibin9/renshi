"""Canonical HR11 permission and cross-domain event definitions."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_time.constants import ALL_TIME_PERMISSIONS


PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key=key, module_code="HR11", description=str(description))
    for key, description in ALL_TIME_PERMISSIONS
)

EVENT_DEFINITIONS = (
    BusinessEventDefinition("hr.time.policy.published", "HR11", "policy", description="Time policy version published"),
    BusinessEventDefinition("hr.time.calendar.published", "HR11", "calendar", description="Work-calendar version published"),
    BusinessEventDefinition("hr.time.attendance_fact.finalized", "HR11", "attendance_fact", description="Attendance fact sealed by close"),
    BusinessEventDefinition("hr.time.leave_request.approved", "HR11", "leave_request", description="Leave request approved"),
    BusinessEventDefinition("hr.time.overtime_fact.verified", "HR11", "overtime_fact", description="Overtime fact verified"),
    BusinessEventDefinition("hr.time.time_close.closed", "HR11", "time_close", description="Immutable time-close snapshot created"),
    BusinessEventDefinition("hr.time.time_close.reopened", "HR11", "time_close", description="Closed period reopened through correction batch"),
)


def register_authority_definitions() -> None:
    register_permissions(PERMISSION_DEFINITIONS)
    register_business_events(EVENT_DEFINITIONS)
