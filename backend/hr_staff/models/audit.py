"""
hr_staff/models/audit.py —— HrStaffAuditEvent 正式业务审计 + HrSensitiveAccessLog 敏感查看审计（总册 §28）。

决策（总册 §4.5）：
- simple-history / HorillaAuditLog   KEEP 作为技术历史辅助
- HrStaffAuditEvent                  NEW 作为正式人员业务审计
- HrSensitiveAccessLog               NEW 作为敏感查看/导出审计

日志防泄漏（§28.3）：禁止记录身份证完整号、银行卡、明文密码、文件完整内容、access token。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrStaffAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.UUIDField(null=True, blank=True, db_index=True)
    person_id = models.UUIDField(null=True, blank=True)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    actor_staff_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    business_type = models.CharField(max_length=64, blank=True, default="")
    business_id = models.CharField(max_length=64, blank=True, default="")
    before_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    after_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    reason = models.CharField(max_length=512, blank=True, default="")
    source = models.CharField(max_length=64, blank=True, default="")
    approval_instance_id = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("HR Staff Audit Event")
        verbose_name_plural = _("HR Staff Audit Events")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "occurred_at"]),
            models.Index(fields=["tenant_id", "action"]),
            models.Index(fields=["tenant_id", "business_type", "business_id"]),
        ]

    def __str__(self):
        return f"[{self.action}] staff={self.staff_id} @ {self.occurred_at.isoformat()}"


class HrSensitiveAccessLog(models.Model):
    """敏感字段 reveal / 敏感导出 审计（总册 §29）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.UUIDField(null=True, blank=True, db_index=True)
    field_code = models.CharField(max_length=64)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=512, blank=True, default="")
    action = models.CharField(max_length=32, default="REVEAL")  # REVEAL / EXPORT / SEARCH
    access_token_ref = models.CharField(max_length=128, blank=True, default="")
    revealed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        verbose_name = _("HR Sensitive Access Log")
        verbose_name_plural = _("HR Sensitive Access Logs")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "revealed_at"]),
            models.Index(fields=["tenant_id", "field_code"]),
        ]

    def __str__(self):
        return f"[{self.action}] {self.field_code} staff={self.staff_id}"
