"""Django permission materialization anchor for HR08."""

from django.db import models

from hr_external.permissions import PERMISSION_DEFINITIONS


class HrExternalPermissionMeta(models.Model):
    """Create assignable canonical permissions without owning a data table."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = tuple(
            (definition.key, definition.description)
            for definition in PERMISSION_DEFINITIONS
        )
