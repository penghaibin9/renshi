"""School-level Integration Hub configuration.

Connections and mappings are infrastructure. They do not become HR01-HR18
business authorities and never store external-system facts as canonical HR data.
"""
from __future__ import annotations

import uuid
from django.core.exceptions import ValidationError
from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("HRINT_APPEND_ONLY")

    def delete(self):
        raise ValueError("HRINT_APPEND_ONLY")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("HRINT_APPEND_ONLY")


class AppendOnlyManager(models.Manager.from_queryset(AppendOnlyQuerySet)):
    pass


class HrIntegrationPermissionMeta(models.Model):
    class Meta:
        managed = False
        app_label = "hr_integration"
        permissions = (
            ("hr.integration.view", "查看高校人事 Integration Hub"),
            ("hr.integration.manage", "维护学校接口与字段映射"),
            ("hr.integration.test", "执行接口连通性测试"),
        )


class IntegrationConnection(HrTenantScopedModel):
    class Category(models.TextChoices):
        SSO = "SSO", "统一认证"
        MASTER_DATA = "MASTER_DATA", "组织人员 / 主数据"
        RESEARCH = "RESEARCH", "科研"
        ACADEMIC = "ACADEMIC", "教务"
        FINANCE = "FINANCE", "财务"
        ATTENDANCE = "ATTENDANCE", "考勤 / 门禁 / 一卡通"
        ESIGN = "ESIGN", "电子签章"
        NOTIFICATION = "NOTIFICATION", "短信 / 邮件 / 企业微信"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "待配置"
        CONFIGURED = "CONFIGURED", "已配置"
        VERIFIED = "VERIFIED", "已验证"
        ERROR = "ERROR", "验证失败"

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=24, choices=Category.choices, db_index=True)
    adapter_code = models.CharField(max_length=64, db_index=True)
    base_url = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=False)
    config_json = models.JSONField(default=dict, blank=True)
    secret_ciphertext = models.TextField(blank=True, default="", editable=False)
    credential_updated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.CharField(max_length=32, blank=True, default="")
    last_test_message = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "hrint_connection"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "code"), name="uq_hrint_tenant_code")
        ]
        indexes = [
            models.Index(fields=("tenant_id", "category", "enabled"), name="idx_hrint_category")
        ]

    def __str__(self):
        return f"{self.category}/{self.code}"

    @property
    def has_credentials(self):
        return bool(self.secret_ciphertext)


class IntegrationMappingProfile(HrTenantScopedModel):
    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "外部 → 人事"
        OUTBOUND = "OUTBOUND", "人事 → 外部"
        BIDIRECTIONAL = "BIDIRECTIONAL", "双向"

    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name="mapping_profiles")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    source_object = models.CharField(max_length=96, blank=True, default="")
    target_domain = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "hrint_mapping_profile"
        constraints = [models.UniqueConstraint(fields=("connection", "code"), name="uq_hrint_mapping_code")]

    def clean(self):
        super().clean()
        if self.connection_id and self.connection.tenant_id != self.tenant_id:
            raise ValidationError("connection tenant mismatch")


class IntegrationFieldMapping(HrTenantScopedModel):
    profile = models.ForeignKey(IntegrationMappingProfile, on_delete=models.CASCADE, related_name="fields")
    source_field = models.CharField(max_length=160)
    target_field = models.CharField(max_length=160)
    transform_code = models.CharField(max_length=64, blank=True, default="DIRECT")
    required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=10)

    class Meta:
        db_table = "hrint_field_mapping"
        constraints = [
            models.UniqueConstraint(fields=("profile", "source_field"), name="uq_hrint_source_field"),
            models.UniqueConstraint(fields=("profile", "sort_order"), name="uq_hrint_mapping_order"),
        ]
        ordering = ("sort_order", "source_field")

    def clean(self):
        super().clean()
        if self.profile_id and self.profile.tenant_id != self.tenant_id:
            raise ValidationError("mapping profile tenant mismatch")


class IntegrationTestRun(models.Model):
    objects = AppendOnlyManager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="test_runs")
    adapter_code = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    summary = models.CharField(max_length=255)
    detail_json = models.JSONField(default=dict, blank=True)
    tested_by = models.PositiveBigIntegerField(null=True, blank=True)
    tested_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hrint_test_run"
        indexes = [models.Index(fields=("tenant_id", "tested_at"), name="idx_hrint_test_tenant")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("HRINT_TEST_RUN_APPEND_ONLY")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HRINT_TEST_RUN_APPEND_ONLY")


class IntegrationAuditEvent(models.Model):
    objects = AppendOnlyManager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    actor_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=64, db_index=True)
    connection_code = models.CharField(max_length=64, blank=True, default="")
    summary = models.CharField(max_length=255)
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hrint_audit_event"
        indexes = [models.Index(fields=("tenant_id", "created_at"), name="idx_hrint_audit_tenant")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("HRINT_AUDIT_APPEND_ONLY")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HRINT_AUDIT_APPEND_ONLY")


class SsoLoginEvidence(models.Model):
    """Append-only SSO runtime evidence. Tokens/tickets/passwords/claims are never stored."""
    objects = AppendOnlyManager()

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "登录成功"
        FAILED = "FAILED", "登录失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="sso_login_evidence")
    protocol = models.CharField(max_length=16)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    runtime_contract_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    subject_fingerprint = models.CharField(max_length=64, blank=True, default="")
    staff_no = models.CharField(max_length=64, blank=True, default="")
    auth_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    detail_json = models.JSONField(default=dict, blank=True)
    happened_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hrint_sso_login_evidence"
        indexes = [models.Index(fields=("tenant_id", "connection", "happened_at"), name="idx_hrint_sso_evidence")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("HRINT_SSO_EVIDENCE_APPEND_ONLY")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HRINT_SSO_EVIDENCE_APPEND_ONLY")
