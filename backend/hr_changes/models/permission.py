"""Database permission metadata for the HR06 canonical permission contract."""

from django.db import models

from hr_changes.constants import HR_CHANGE_PERMISSIONS


class HrChangePermissionMeta(models.Model):
    """Unmanaged model whose custom permissions are materialized post-migrate."""

    class Meta:
        managed = False
        app_label = "hr_changes"
        permissions = tuple(
            (code, code.replace(".", " ").title())
            for code in HR_CHANGE_PERMISSIONS
        )
