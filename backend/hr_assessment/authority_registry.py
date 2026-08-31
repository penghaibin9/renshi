"""Canonical HR12 permission and cross-domain event definitions."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_assessment.permissions import ASSESSMENT_PERMISSIONS


EVENT_RESULT_CORRECTED = "hr.assessment.assessment_result.corrected"
EVENT_RESULT_REVOKED = "hr.assessment.assessment_result.revoked"


PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key=key, module_code="HR12", description=description)
    for key, description in ASSESSMENT_PERMISSIONS
)

EVENT_DEFINITIONS = (
    BusinessEventDefinition("hr.assessment.assessment_policy.published", "HR12", "assessment_policy", description="Assessment policy version published"),
    BusinessEventDefinition("hr.assessment.assessment_cycle.opened", "HR12", "assessment_cycle", description="Assessment cycle opened"),
    BusinessEventDefinition("hr.assessment.assessment_population.frozen", "HR12", "assessment_population", description="Cycle population frozen"),
    BusinessEventDefinition("hr.assessment.assessment_result.finalized", "HR12", "assessment_result", description="Formal assessment result finalized"),
    BusinessEventDefinition("hr.assessment.assessment_objection.submitted", "HR12", "assessment_objection", description="Assessment objection submitted"),
    BusinessEventDefinition("hr.assessment.assessment_objection.decided", "HR12", "assessment_objection", description="Assessment objection decided"),
    BusinessEventDefinition("hr.assessment.assessment_result.revised", "HR12", "assessment_result", description="Formal result revised through version chain"),
    BusinessEventDefinition(EVENT_RESULT_CORRECTED, "HR12", "assessment_result", description="Sealed assessment result corrected by append-only fact"),
    BusinessEventDefinition(EVENT_RESULT_REVOKED, "HR12", "assessment_result", description="Sealed assessment result revoked by append-only fact"),
    BusinessEventDefinition("hr.assessment.term_assessment.finalized", "HR12", "term_assessment", description="Term assessment finalized"),
)


def register_authority_definitions() -> None:
    register_permissions(PERMISSION_DEFINITIONS)
    register_business_events(EVENT_DEFINITIONS)
