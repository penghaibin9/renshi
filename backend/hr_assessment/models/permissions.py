"""Django permission materialization anchor for HR12."""

from django.db import models

from hr_assessment.permissions import ASSESSMENT_PERMISSIONS


class HrAssessmentPermissionMeta(models.Model):
    """Create assignable canonical permissions without owning a data table."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = tuple(ASSESSMENT_PERMISSIONS)
