"""
hr10_development/models/audit.py

HR10 审计事件模型。
记录所有写操作的 before/after、actor、tenant、correlation。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentAuditEvent(DevelopmentTenantModel):
    """HR10 业务审计日志。"""

    actor_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("操作人"),
    )

    on_behalf_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("代理操作人"),
    )

    object_type = models.CharField(
        max_length=128,
        verbose_name=_("对象类型"),
    )

    object_id = models.CharField(
        max_length=64,
        verbose_name=_("对象 ID"),
    )

    action = models.CharField(
        max_length=128,
        verbose_name=_("动作"),
    )

    before_json = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("修改前"),
    )

    after_json = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("修改后"),
    )

    revision_ref = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("修订引用"),
    )

    reason = models.TextField(
        blank=True,
        default="",
        verbose_name=_("原因"),
    )

    request_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("请求 ID"),
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP 地址"),
    )

    class Meta:
        db_table = "hr_development_audit_event"
        verbose_name = _("发展审计事件")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["tenant_id", "object_type", "object_id"]),
            models.Index(fields=["tenant_id", "actor_id", "created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.object_type}.{self.action} by {self.actor_id}"
