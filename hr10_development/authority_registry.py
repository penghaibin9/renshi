"""Canonical HR10 permission and cross-domain event definitions."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr10_development.permissions import HR10_PERMISSIONS


PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key=key, module_code="HR10", description=f"HR10 development action: {key}")
    for key in HR10_PERMISSIONS
)

EVENT_DEFINITIONS = (
    BusinessEventDefinition("hr.development.development_plan.published", "HR10", "development_plan", description="Frozen development-plan version published"),
    BusinessEventDefinition("hr.development.learning_completion.verified", "HR10", "learning_completion", description="Training completion evidence verified"),
    BusinessEventDefinition("hr.development.practice_evaluation.finalized", "HR10", "practice_evaluation", description="Enterprise-practice evaluation finalized"),
    BusinessEventDefinition("hr.development.development_fact.verified", "HR10", "development_fact", description="Formal development fact verified"),
    BusinessEventDefinition("hr.development.development_fact.superseded", "HR10", "development_fact", description="Formal development fact superseded by a new version"),
)


def register_authority_definitions() -> None:
    register_permissions(PERMISSION_DEFINITIONS)
    register_business_events(EVENT_DEFINITIONS)
