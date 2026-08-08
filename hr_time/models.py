"""
hr_time/models.py

S1 阶段仅注册 HR11 权限元数据（总册 §151）。业务模型随 S2-S9 按
阶段创建（Policy/Calendar/Shift/Schedule/Event/Fact/Leave/Close…），
并全部遵循：
- tenant_id NOT NULL（A0 fail-closed 的 DB 层约束）；
- 发布后版本 immutable guard；
- 事件 append-only。
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
