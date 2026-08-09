"""
hr_onboarding/models/template.py

Onboarding Template（总册 §18/§19/§1.4）：
- 模板必须独立于 Recruitment（缺陷 A 修复）；
- Case 创建时绑定 version，后面改模板不影响旧 Case；
- 多版本同优先级命中必须显式 CONFIGURATION_CONFLICT，禁止 .first()。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import (
    BlockingLevel,
    ResponsibleRole,
    TaskCompletionType,
)


class HrOnboardingTemplate(models.Model):
    """可复用入职模板（独立于 Recruitment 的产品对象）。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        ACTIVE = "ACTIVE", _("Active")
        ARCHIVED = "ARCHIVED", _("Archived")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    applicable_staff_categories = models.JSONField(default=list, blank=True)
    applicable_employment_types = models.JSONField(default=list, blank=True)
    applicable_post_categories = models.JSONField(default=list, blank=True)
    applicable_organizations = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Template")
        verbose_name_plural = _("HR Onboarding Templates")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_ob_template_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.code} ({self.name})"


class HrOnboardingTemplateVersion(models.Model):
    """模板版本：Case 创建时冻结版本，禁止模板变更污染历史（总册 §18/§66.22）。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        ACTIVE = "ACTIVE", _("Active")
        RETIRED = "RETIRED", _("Retired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template = models.ForeignKey(
        HrOnboardingTemplate,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_no = models.PositiveIntegerField(default=1)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    snapshot_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Template Version")
        verbose_name_plural = _("HR Onboarding Template Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version_no"],
                name="uniq_hr_ob_template_version_no",
            ),
        ]

    def __str__(self):
        return f"{self.template.code} v{self.version_no}"


class HrOnboardingStageDefinition(models.Model):
    """阶段定义（用户理解层，Task 才是实际工作，总册 §37）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template_version = models.ForeignKey(
        HrOnboardingTemplateVersion,
        on_delete=models.CASCADE,
        related_name="stage_definitions",
    )
    code = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    sequence = models.IntegerField(default=0)
    is_final = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Stage Definition")
        verbose_name_plural = _("HR Onboarding Stage Definitions")
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "code"],
                name="uniq_hr_ob_stage_def_template_code",
            ),
        ]
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.code} ({self.title})"


class HrOnboardingTaskDefinition(models.Model):
    """任务定义（总册 §14.2）—— is_required 单布尔升级为 blocking_level。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template_version = models.ForeignKey(
        HrOnboardingTemplateVersion,
        on_delete=models.CASCADE,
        related_name="task_definitions",
    )
    code = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=64, blank=True, default="")
    responsible_role = models.CharField(
        max_length=32,
        choices=ResponsibleRole.choices,
        default=ResponsibleRole.RESPONSIBLE_HR,
    )
    due_offset_days = models.IntegerField(default=0)
    available_offset_days = models.IntegerField(default=0)
    blocking_level = models.CharField(
        max_length=32,
        choices=BlockingLevel.choices,
        default=BlockingLevel.NON_BLOCKING,
    )
    prerequisite_codes = models.JSONField(default=list, blank=True)
    completion_type = models.CharField(
        max_length=16,
        choices=TaskCompletionType.choices,
        default=TaskCompletionType.MANUAL,
    )
    automation_handler = models.CharField(max_length=128, blank=True, default="")
    candidate_visible = models.BooleanField(default=True)
    sequence = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Task Definition")
        verbose_name_plural = _("HR Onboarding Task Definitions")
        constraints = [
            models.UniqueConstraint(
                fields=["template_version", "code"],
                name="uniq_hr_ob_task_def_template_code",
            ),
        ]
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.code} ({self.title})"
