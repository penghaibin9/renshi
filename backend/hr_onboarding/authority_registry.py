"""HR05 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions


CANONICAL_PERMISSION_KEYS = (
    "hr.onboarding.case.view",
    "hr.onboarding.case.create",
    "hr.onboarding.case.cancel",
    "hr.onboarding.case.activate",
    "hr.onboarding.activation_fact.correct",
    "hr.onboarding.activation_fact.revoke",
    "hr.onboarding.report.checkin",
    "hr.onboarding.material.review",
    "hr.onboarding.material.sensitive_view",
    "hr.onboarding.task.manage",
    "hr.onboarding.task.complete",
    "hr.onboarding.task.waive",
    "hr.onboarding.identity.provision",
    "hr.onboarding.position.commit",
    "hr.onboarding.probation.manage",
    "hr.onboarding.probation.finalize",
    "hr.onboarding.export.standard",
    "hr.onboarding.export.sensitive",
)
PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key, "HR05", f"HR05 Authority: {key}")
    for key in CANONICAL_PERMISSION_KEYS
)
register_permissions(PERMISSION_DEFINITIONS)


EVENT_CASE_CREATED = "hr.onboarding.case.created"
EVENT_PREHIRE_CONFIRMED = "hr.onboarding.prehire.confirmed"
EVENT_EMPLOYEE_REPORTED = "hr.onboarding.employee.reported"
EVENT_STAFF_ACTIVATED = "hr.onboarding.staff.activated"
EVENT_ACTIVATION_FACT_CORRECTED = "hr.onboarding.activation_fact.corrected"
EVENT_ACTIVATION_FACT_REVOKED = "hr.onboarding.activation_fact.revoked"
EVENT_ONBOARDING_COMPLETED = "hr.onboarding.onboarding.completed"
EVENT_PROBATION_CONFIRMED = "hr.onboarding.probation.confirmed"
EVENT_PROBATION_FAILED = "hr.onboarding.probation.failed"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_CASE_CREATED, "HR05", "case", 1),
    BusinessEventDefinition(EVENT_PREHIRE_CONFIRMED, "HR05", "prehire", 1),
    BusinessEventDefinition(EVENT_EMPLOYEE_REPORTED, "HR05", "employee", 1),
    BusinessEventDefinition(EVENT_STAFF_ACTIVATED, "HR05", "staff", 1),
    BusinessEventDefinition(
        EVENT_ACTIVATION_FACT_CORRECTED, "HR05", "activation_fact", 1
    ),
    BusinessEventDefinition(
        EVENT_ACTIVATION_FACT_REVOKED, "HR05", "activation_fact", 1
    ),
    BusinessEventDefinition(EVENT_ONBOARDING_COMPLETED, "HR05", "onboarding", 1),
    BusinessEventDefinition(EVENT_PROBATION_CONFIRMED, "HR05", "probation", 1),
    BusinessEventDefinition(EVENT_PROBATION_FAILED, "HR05", "probation", 1),
)
register_business_events(EVENT_DEFINITIONS)
