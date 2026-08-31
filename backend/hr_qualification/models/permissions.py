"""Django permission materialization anchor for HR09."""

from django.db import models

from hr_qualification.permissions import PERMISSION_DEFINITIONS


# These two permissions already belong to HrDoubleTeacherFinalDecision since
# migration 0006. Keeping that ownership avoids duplicate auth_permission rows
# while the anchor materializes the remainder of the canonical registry.
EXISTING_FINAL_DECISION_PERMISSION_KEYS = frozenset(
    {
        "hr.qualification.review.final_decision.correct",
        "hr.qualification.review.final_decision.revoke",
    }
)


class HrQualificationPermissionMeta(models.Model):
    """Create the HR09 permissions not already owned by a business model."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = tuple(
            (definition.key, definition.description)
            for definition in PERMISSION_DEFINITIONS
            if definition.key not in EXISTING_FINAL_DECISION_PERMISSION_KEYS
        )
