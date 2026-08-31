"""HR06 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_changes.constants import HR_CHANGE_PERMISSIONS


CANONICAL_PERMISSION_KEYS = HR_CHANGE_PERMISSIONS
PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key, "HR06", f"HR06 Authority: {key}")
    for key in CANONICAL_PERMISSION_KEYS
)
register_permissions(PERMISSION_DEFINITIONS)


EVENT_CHANGE_SUBMITTED = "hr.change.personnel_change.submitted"
EVENT_CHANGE_APPROVED = "hr.change.personnel_change.approved"
EVENT_CHANGE_EFFECTIVE = "hr.change.personnel_change.effective"
EVENT_CHANGE_CORRECTED = "hr.change.personnel_change.corrected"
EVENT_CHANGE_RESCINDED = "hr.change.personnel_change.rescinded"
EVENT_CHANGE_APPLY_FAILED = "hr.change.personnel_change.apply_failed"
EVENT_CONTRACT_REVIEW_REQUIRED = "hr.change.contract_review.required"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_CHANGE_SUBMITTED, "HR06", "personnel_change", 1),
    BusinessEventDefinition(EVENT_CHANGE_APPROVED, "HR06", "personnel_change", 1),
    BusinessEventDefinition(EVENT_CHANGE_EFFECTIVE, "HR06", "personnel_change", 1),
    BusinessEventDefinition(EVENT_CHANGE_CORRECTED, "HR06", "personnel_change", 1),
    BusinessEventDefinition(EVENT_CHANGE_RESCINDED, "HR06", "personnel_change", 1),
    BusinessEventDefinition(EVENT_CHANGE_APPLY_FAILED, "HR06", "personnel_change", 1),
    BusinessEventDefinition(
        EVENT_CONTRACT_REVIEW_REQUIRED, "HR06", "contract_review", 1
    ),
)
register_business_events(EVENT_DEFINITIONS)
