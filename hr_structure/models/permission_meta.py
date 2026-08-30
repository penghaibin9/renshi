"""Database permission metadata for the HR02 canonical permission contract."""

from django.db import models

from hr_structure.permissions import HR02_PERMISSIONS


class HrStructurePermissionMeta(models.Model):
    """Managed=False model used only by Django's permission creation hook."""

    class Meta:
        managed = False
        permissions = tuple(
            (code, code.replace("hr.", "HR ").replace(".", ": ").title())
            for code in HR02_PERMISSIONS
        )
