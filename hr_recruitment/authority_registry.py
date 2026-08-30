"""HR04 canonical permission and business-event registrations."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions


CANONICAL_PERMISSION_KEYS = (
    "hr.recruitment.plan.view",
    "hr.recruitment.plan.create",
    "hr.recruitment.plan.approve",
    "hr.recruitment.campaign.view",
    "hr.recruitment.campaign.manage",
    "hr.recruitment.campaign.publish",
    "hr.recruitment.application.view",
    "hr.recruitment.application.manage",
    "hr.recruitment.application.sensitive_view",
    "hr.recruitment.application.export",
    "hr.recruitment.qualification.review",
    "hr.recruitment.qualification.finalize",
    "hr.recruitment.assessment.manage",
    "hr.recruitment.assessment.score",
    "hr.recruitment.assessment.score.override",
    "hr.recruitment.assessment.unlock_score",
    "hr.recruitment.proposed_hire.manage",
    "hr.recruitment.public_notice.publish",
    "hr.recruitment.offer.manage",
    "hr.recruitment.handoff_hr05.execute",
)
PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(key, "HR04", f"HR04 Authority: {key}")
    for key in CANONICAL_PERMISSION_KEYS
)
register_permissions(PERMISSION_DEFINITIONS)


EVENT_PLAN_REQUEST_SUBMITTED = "hr.recruitment.plan_request.submitted"
EVENT_PLAN_REQUEST_APPROVED = "hr.recruitment.plan_request.approved"
EVENT_CAMPAIGN_CREATED = "hr.recruitment.campaign.created"
EVENT_MEDICAL_CHECK_RECORDED = "hr.recruitment.medical_check.recorded"
EVENT_BACKGROUND_CHECK_RECORDED = "hr.recruitment.background_check.recorded"
EVENT_HANDOFF_CREATED = "hr.recruitment.handoff.created"
EVENT_SCORE_SUBMITTED = "hr.recruitment.score_sheet.submitted"
EVENT_SCORE_LOCKED = "hr.recruitment.score_sheet.locked"
EVENT_SCORE_REOPENED = "hr.recruitment.score_sheet.reopened"
EVENT_SCORE_REOPEN_REQUESTED = "hr.recruitment.score_sheet.reopen_requested"
EVENT_SCORE_REOPEN_APPROVED = "hr.recruitment.score_sheet.reopen_approved"
EVENT_SCORE_OVERRIDE_ACCESSED = "hr.recruitment.score_sheet.override_accessed"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_PLAN_REQUEST_SUBMITTED, "HR04", "plan_request", 1),
    BusinessEventDefinition(EVENT_PLAN_REQUEST_APPROVED, "HR04", "plan_request", 1),
    BusinessEventDefinition(EVENT_CAMPAIGN_CREATED, "HR04", "campaign", 1),
    BusinessEventDefinition(EVENT_MEDICAL_CHECK_RECORDED, "HR04", "medical_check", 1),
    BusinessEventDefinition(
        EVENT_BACKGROUND_CHECK_RECORDED, "HR04", "background_check", 1
    ),
    BusinessEventDefinition(EVENT_HANDOFF_CREATED, "HR04", "handoff", 1),
    BusinessEventDefinition(EVENT_SCORE_SUBMITTED, "HR04", "score_sheet", 1),
    BusinessEventDefinition(EVENT_SCORE_LOCKED, "HR04", "score_sheet", 1),
    BusinessEventDefinition(EVENT_SCORE_REOPENED, "HR04", "score_sheet", 1),
    BusinessEventDefinition(
        EVENT_SCORE_REOPEN_REQUESTED, "HR04", "score_sheet", 1
    ),
    BusinessEventDefinition(EVENT_SCORE_REOPEN_APPROVED, "HR04", "score_sheet", 1),
    BusinessEventDefinition(
        EVENT_SCORE_OVERRIDE_ACCESSED, "HR04", "score_sheet", 1
    ),
)
register_business_events(EVENT_DEFINITIONS)
