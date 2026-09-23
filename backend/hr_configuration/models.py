"""School-level configurable workflow contracts for HR04/05/06/12/13/14/16/17.

This is infrastructure, not HR19.  It never owns employee/recruitment/payroll facts.
Published workflow versions are immutable snapshots consumed through
``hr_configuration.services.get_published_workflow_config``.
"""
from __future__ import annotations

import uuid
from django.core.exceptions import ValidationError
from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


class HrConfigurationPermissionMeta(models.Model):
    class Meta:
        managed = False
        app_label = "hr_configuration"
        permissions = (
            ("hr.configuration.view", "查看高校人事配置中心"),
            ("hr.configuration.manage", "编辑高校人事配置草稿"),
            ("hr.configuration.publish", "发布高校人事流程配置"),
        )


class WorkflowDefinition(HrTenantScopedModel):
    """Stable school-owned identity for one configurable HR workflow."""

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    business_domain = models.CharField(max_length=16, db_index=True)
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "hrcfg_workflow_definition"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "code"), name="uq_hrcfg_workflow_tenant_code"
            )
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "business_domain", "enabled"),
                name="idx_hrcfg_workflow_domain",
            )
        ]

    def __str__(self):
        return f"{self.business_domain}/{self.code}"


class WorkflowVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(status="PUBLISHED").exists():
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if any(getattr(obj, "status", None) == "PUBLISHED" for obj in objs):
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def delete(self):
        if self.filter(status="PUBLISHED").exists():
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().delete()


class WorkflowVersion(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PUBLISHED = "PUBLISHED", "已发布"

    workflow = models.ForeignKey(
        WorkflowDefinition, on_delete=models.PROTECT, related_name="versions"
    )
    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    change_note = models.CharField(max_length=255, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.PositiveBigIntegerField(null=True, blank=True)

    objects = WorkflowVersionQuerySet.as_manager()

    class Meta:
        db_table = "hrcfg_workflow_version"
        constraints = [
            models.UniqueConstraint(
                fields=("workflow", "version_no"), name="uq_hrcfg_workflow_version"
            )
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "published_at"),
                name="idx_hrcfg_version_status",
            )
        ]

    def clean(self):
        super().clean()
        if self.workflow_id and self.workflow.tenant_id != self.tenant_id:
            raise ValidationError("workflow tenant mismatch")

    def save(self, *args, **kwargs):
        if self.pk:
            current_status = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            # A published snapshot is write-once.  Publishing itself transitions a DRAFT row,
            # but every later ORM save is rejected regardless of which field changed.
            if current_status == self.Status.PUBLISHED:
                raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.PUBLISHED:
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().delete(*args, **kwargs)


class DraftChildQuerySet(models.QuerySet):
    def _guard(self):
        if self.filter(version__status="PUBLISHED").exists():
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")

    def update(self, **kwargs):
        self._guard()
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if any(getattr(getattr(obj, "version", None), "status", None) == "PUBLISHED" for obj in objs):
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        objs=list(objs)
        if any(getattr(getattr(obj, "version", None), "status", None) == "PUBLISHED" for obj in objs):
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().bulk_create(objs,batch_size=batch_size,ignore_conflicts=ignore_conflicts,update_conflicts=update_conflicts,update_fields=update_fields,unique_fields=unique_fields)

    def delete(self):
        self._guard()
        return super().delete()


class VersionChild(HrTenantScopedModel):
    version = models.ForeignKey(WorkflowVersion, on_delete=models.CASCADE)

    objects = DraftChildQuerySet.as_manager()

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.version_id:
            if self.version.tenant_id != self.tenant_id:
                raise ValidationError("workflow version tenant mismatch")
            if self.version.status != WorkflowVersion.Status.DRAFT:
                raise ValidationError("published workflow configuration is immutable")

    def save(self, *args, **kwargs):
        if self.version_id and self.version.status != WorkflowVersion.Status.DRAFT:
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.version_id and self.version.status != WorkflowVersion.Status.DRAFT:
            raise ValueError("HRCFG_PUBLISHED_IMMUTABLE")
        return super().delete(*args, **kwargs)


class WorkflowStage(VersionChild):
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=10)
    is_start = models.BooleanField(default=False)
    is_end = models.BooleanField(default=False)

    class Meta:
        db_table = "hrcfg_workflow_stage"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_stage_code"),
            models.UniqueConstraint(fields=("version", "sort_order"), name="uq_hrcfg_stage_order"),
        ]
        ordering = ("sort_order", "code")


class FormDefinition(VersionChild):
    code = models.CharField(max_length=64)
    title = models.CharField(max_length=160)
    stage_code = models.CharField(max_length=64, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=10)
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "hrcfg_form_definition"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_form_code")
        ]
        ordering = ("sort_order", "code")


class FieldDefinition(VersionChild):
    class FieldType(models.TextChoices):
        TEXT = "TEXT", "单行文本"
        TEXTAREA = "TEXTAREA", "多行文本"
        INTEGER = "INTEGER", "整数"
        DECIMAL = "DECIMAL", "小数"
        DATE = "DATE", "日期"
        DATETIME = "DATETIME", "日期时间"
        BOOLEAN = "BOOLEAN", "是/否"
        SELECT = "SELECT", "单选下拉"
        MULTISELECT = "MULTISELECT", "多选"
        FILE = "FILE", "附件"

    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="fields")
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=16, choices=FieldType.choices, default=FieldType.TEXT)
    required = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=10)
    help_text = models.CharField(max_length=255, blank=True, default="")
    default_value = models.CharField(max_length=255, blank=True, default="")
    options_json = models.JSONField(default=list, blank=True)
    validation_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "hrcfg_field_definition"
        constraints = [
            models.UniqueConstraint(fields=("version", "key"), name="uq_hrcfg_field_key"),
            models.UniqueConstraint(fields=("form", "sort_order"), name="uq_hrcfg_field_order"),
        ]
        ordering = ("form_id", "sort_order", "key")

    def clean(self):
        super().clean()
        if self.form_id and self.form.version_id != self.version_id:
            raise ValidationError("form/version mismatch")


class ApprovalRoleRule(VersionChild):
    class ApprovalMode(models.TextChoices):
        ANY = "ANY", "任一人通过"
        ALL = "ALL", "全部通过"
        SEQUENTIAL = "SEQUENTIAL", "按顺序审批"

    code = models.CharField(max_length=64)
    stage_code = models.CharField(max_length=64)
    role_code = models.CharField(max_length=96)
    role_name = models.CharField(max_length=120)
    data_scope = models.CharField(max_length=32, default="SAME_ORG")
    sort_order = models.PositiveIntegerField(default=10)
    approval_mode = models.CharField(max_length=16, choices=ApprovalMode.choices, default=ApprovalMode.ANY)

    class Meta:
        db_table = "hrcfg_approval_role_rule"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_approval_code")
        ]
        ordering = ("sort_order", "code")


class ConditionRule(VersionChild):
    class Operator(models.TextChoices):
        EQ = "EQ", "等于"
        NE = "NE", "不等于"
        GT = "GT", "大于"
        GTE = "GTE", "大于等于"
        LT = "LT", "小于"
        LTE = "LTE", "小于等于"
        IN = "IN", "属于"
        NOT_IN = "NOT_IN", "不属于"
        EMPTY = "EMPTY", "为空"
        NOT_EMPTY = "NOT_EMPTY", "不为空"

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    source_stage_code = models.CharField(max_length=64)
    field_key = models.CharField(max_length=64)
    operator = models.CharField(max_length=16, choices=Operator.choices)
    compare_value_json = models.JSONField(default=dict, blank=True)
    target_stage_code = models.CharField(max_length=64)
    priority = models.PositiveIntegerField(default=100)

    class Meta:
        db_table = "hrcfg_condition_rule"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_condition_code")
        ]
        ordering = ("priority", "code")


class NotificationRule(VersionChild):
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "站内通知"
        EMAIL = "EMAIL", "邮件"
        SMS = "SMS", "短信"
        WECOM = "WECOM", "企业微信"

    code = models.CharField(max_length=64)
    event_code = models.CharField(max_length=64)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    recipient_role_code = models.CharField(max_length=96)
    subject_template = models.CharField(max_length=200, blank=True, default="")
    body_template = models.TextField()
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "hrcfg_notification_rule"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_notification_code")
        ]


class PrintTemplate(VersionChild):
    class OutputFormat(models.TextChoices):
        HTML = "HTML", "HTML/浏览器打印"
        PDF = "PDF", "PDF"

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    output_format = models.CharField(max_length=8, choices=OutputFormat.choices, default=OutputFormat.PDF)
    template_body = models.TextField()
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "hrcfg_print_template"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_print_code")
        ]


class ExcelTemplate(VersionChild):
    class Direction(models.TextChoices):
        IMPORT = "IMPORT", "导入"
        EXPORT = "EXPORT", "导出"
        BOTH = "BOTH", "导入/导出"

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    direction = models.CharField(max_length=8, choices=Direction.choices, default=Direction.IMPORT)
    sheet_name = models.CharField(max_length=31, default="数据")
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "hrcfg_excel_template"
        constraints = [
            models.UniqueConstraint(fields=("version", "code"), name="uq_hrcfg_excel_code")
        ]


class ExcelColumn(VersionChild):
    template = models.ForeignKey(ExcelTemplate, on_delete=models.CASCADE, related_name="columns")
    field_key = models.CharField(max_length=64)
    header = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=10)
    required = models.BooleanField(default=False)
    data_type = models.CharField(max_length=24, default="TEXT")
    example_value = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "hrcfg_excel_column"
        constraints = [
            models.UniqueConstraint(fields=("template", "field_key"), name="uq_hrcfg_excel_field"),
            models.UniqueConstraint(fields=("template", "sort_order"), name="uq_hrcfg_excel_order"),
        ]
        ordering = ("sort_order", "field_key")

    def clean(self):
        super().clean()
        if self.template_id and self.template.version_id != self.version_id:
            raise ValidationError("excel template/version mismatch")


class ConfigurationAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("HRCFG_AUDIT_APPEND_ONLY")

    def delete(self):
        raise ValueError("HRCFG_AUDIT_APPEND_ONLY")


class ConfigurationAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.PositiveBigIntegerField(db_index=True)
    actor_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    summary = models.CharField(max_length=255)
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ConfigurationAuditQuerySet.as_manager()

    class Meta:
        db_table = "hrcfg_audit_event"
        indexes = [
            models.Index(fields=("tenant_id", "created_at"), name="idx_hrcfg_audit_tenant")
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("HRCFG_AUDIT_APPEND_ONLY")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HRCFG_AUDIT_APPEND_ONLY")
