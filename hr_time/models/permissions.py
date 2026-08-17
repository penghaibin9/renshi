"""
hr_time/models/permissions.py

HR11 权限元数据（总册 §151）。仅注册权限码，无数据字段。
"""

from django.db import models

from hr_time.constants import ALL_TIME_PERMISSIONS


class HrTimePermissionMeta(models.Model):
    """仅为注册 HR11 权限码（总册 §151），无数据字段。"""

    class Meta:
        managed = False
        permissions = tuple(
            (code, str(verbose)) for code, verbose in ALL_TIME_PERMISSIONS
        )
