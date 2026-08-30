"""HR03 canonical Authority permission/event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_staff.constants import HR03_EVENT_TYPES, HR_STAFF_PERMISSIONS


PERM_PERSONNEL_DECISION_VIEW = "hr.staff.personnel_decision.view"
PERM_PERSONNEL_DECISION_MANAGE = "hr.staff.personnel_decision.manage"
PERM_REWARD_DISCIPLINARY_VIEW = "hr.staff.reward_disciplinary.view"
PERM_REWARD_DISCIPLINARY_MANAGE = "hr.staff.reward_disciplinary.manage"

PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(code, "HR03", code.replace("hr.staff.", "").replace(".", " "))
    for code in HR_STAFF_PERMISSIONS
)
register_permissions(PERMISSION_DEFINITIONS)

EVENT_PERSONNEL_DECISION_EFFECTIVE = "hr.staff.personnel_decision.effective"
EVENT_REWARD_DISCIPLINARY_EFFECTIVE = "hr.staff.reward_disciplinary.effective"

_EVENT_AGGREGATES = {
    "hr.staff.staff.created": "staff",
    "hr.staff.staff.activated": "staff",
    "hr.staff.staff.status_changed": "staff",
    "hr.staff.employment_relationship.started": "employment_relationship",
    "hr.staff.employment_relationship.ended": "employment_relationship",
    "hr.staff.assignment.primary_changed": "assignment",
    "hr.staff.assignment.concurrent_changed": "assignment",
    "hr.staff.staff.basic_info_corrected": "staff",
    "hr.staff.credential.changed": "credential",
    "hr.staff.material.verified": "material",
    "hr.staff.authority_mode.changed": "authority_mode",
    EVENT_PERSONNEL_DECISION_EFFECTIVE: "personnel_decision",
    EVENT_REWARD_DISCIPLINARY_EFFECTIVE: "reward_disciplinary",
}

EVENT_DEFINITIONS = tuple(
    BusinessEventDefinition(name, "HR03", _EVENT_AGGREGATES[name], 1)
    for name in sorted(HR03_EVENT_TYPES)
)
register_business_events(EVENT_DEFINITIONS)

LEGACY_EVENT_TYPE_ALIASES = {
    "StaffCreated": "hr.staff.staff.created",
    "StaffActivated": "hr.staff.staff.activated",
    "StaffStatusChanged": "hr.staff.staff.status_changed",
    "EmploymentRelationshipStarted": "hr.staff.employment_relationship.started",
    "EmploymentRelationshipEnded": "hr.staff.employment_relationship.ended",
    "PrimaryAssignmentChanged": "hr.staff.assignment.primary_changed",
    "ConcurrentAssignmentChanged": "hr.staff.assignment.concurrent_changed",
    "StaffBasicInfoCorrected": "hr.staff.staff.basic_info_corrected",
    "StaffCredentialChanged": "hr.staff.credential.changed",
    "StaffMaterialVerified": "hr.staff.material.verified",
    "StaffAuthorityModeChanged": "hr.staff.authority_mode.changed",
}


def canonicalize_hr03_event_type(event_type: str) -> str:
    """Return the canonical v1 event name while accepting old internal aliases."""

    return LEGACY_EVENT_TYPE_ALIASES.get(event_type, event_type)
