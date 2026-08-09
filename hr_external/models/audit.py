"""
hr_external/models/audit.py —— HrExternalAuditEvent + HrSensitiveExternalAccessLog（S2，总册 §109）。

- 正式业务审计：建 Profile / identity match / 敏感查看 / Hiring 提交审批 / Ethics / Conflict /
  Agreement activation / Access grant / Task / Workload / Renewal / Exit / Access revoke /
  Export / Legacy repair（§109）。
- 日志禁止身份证完整号/银行卡/明文密码/文件内容/access token（00 §37/§45）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrExternalAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    external_profile_id = models.UUIDField(null=True, blank=True, db_index=True)
    engagement_id = models.UUIDField(null=True, blank=True, db_index=True)
    task_id = models.UUIDField(null=True, blank=True)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    business_type = models.CharField(max_length=64, blank=True, default="")
    business_id = models.CharField(max_length=64, blank=True, default="")
    before_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    after_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    reason = models.CharField(max_length=512, blank=True, default="")
    source = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("HR External Audit Event")
        verbose_name_plural = _("HR External Audit Events")
        indexes = [
            models.Index(
                fields=["tenant_id", "external_profile_id", "occurred_at"],
                name="hr_external_audit_profile_time_idx",
            ),
            models.Index(
                fields=["tenant_id", "engagement_id", "occurred_at"],
                name="hr_external_audit_eng_time_idx",
            ),
            models.Index(
                fields=["tenant_id", "business_type", "business_id"],
                name="hr_external_audit_biz_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.action}"


class HrSensitiveExternalAccessLog(models.Model):
    """敏感查看/导出审计（§109）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    external_profile_id = models.UUIDField(null=True, blank=True, db_index=True)
    field_code = models.CharField(max_length=64)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=512, blank=True, default="")
    action = models.CharField(max_length=32, default="REVEAL")
    access_token_ref = models.CharField(max_length=128, blank=True, default="")
    revealed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        verbose_name = _("HR Sensitive External Access Log")
        verbose_name_plural = _("HR Sensitive External Access Logs")
        indexes = [
            models.Index(
                fields=["tenant_id", "external_profile_id", "revealed_at"],
                name="hr_external_sens_access_profile_idx",
            ),
            models.Index(
                fields=["tenant_id", "field_code"],
                name="hr_external_sens_access_field_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.field_code} {self.action}"
