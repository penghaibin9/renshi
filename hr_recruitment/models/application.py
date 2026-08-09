"""
hr_recruitment/models/application.py

HR04-03 应聘申请（《04_HR04_总册》§10.4/§14）。

HrJobApplication
  ├─ HrApplicationTransition[]   （状态迁移 ledger，§14.3，每次变化必写）
  ├─ HrApplicationMaterial[]     （材料版本化 + SHA-256 + 验证状态）
  └─ 引用冻结的公告/资格/评分方案版本（不可静默改旧申请）

硬规则：
- canonical_status 权威状态机与 policies/state_machine.py 一致；禁止直接改字段跳态。
- 每次状态变化必须写 HrApplicationTransition ledger。
- unique(tenant, candidate, position, active) 防止重复 active 申请（§10.4）。
- 已提交 Application 的原始快照不可静默改（§51）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    ApplicationCanonicalStatus,
    ApplicationSourceChannel,
    MaterialType,
    MaterialVerificationStatus,
    SensitiveLevel,
)


class HrJobApplication(models.Model):
    """一次应聘申请。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    candidate_id = models.ForeignKey(
        "hr_recruitment.HrRecruitmentCandidate",
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name=_("Candidate"),
    )
    recruitment_position_id = models.ForeignKey(
        "hr_recruitment.HrRecruitmentPosition",
        on_delete=models.PROTECT,
        related_name="applications",
        verbose_name=_("Recruitment Position"),
    )
    application_no = models.CharField(max_length=64, blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    canonical_status = models.CharField(
        max_length=24,
        choices=ApplicationCanonicalStatus.choices,
        default=ApplicationCanonicalStatus.DRAFT,
    )
    workflow_stage_id = models.UUIDField(null=True, blank=True, db_index=True)
    workflow_stage_name = models.CharField(max_length=100, blank=True, default="")
    current_owner_id = models.CharField(max_length=128, blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True)
    source_channel = models.CharField(
        max_length=24,
        choices=ApplicationSourceChannel.choices,
        default=ApplicationSourceChannel.PUBLIC_PORTAL,
    )
    # 冻结的版本引用（发布后不可静默改）
    announcement_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    qualification_rule_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    selection_scheme_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    form_snapshot = models.JSONField(default=dict, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    final_decision_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    legacy_candidate_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Job Application")
        verbose_name_plural = _("Job Applications")
        constraints = [
            # 同候选同岗位最多一个 active 申请
            models.UniqueConstraint(
                fields=["tenant_id", "candidate_id", "recruitment_position_id", "is_active"],
                condition=models.Q(is_active=True),
                name="uniq_hr_application_active_per_position",
            ),
            # application_no tenant 内唯一（§46 兜底，防并发撞号）
            models.UniqueConstraint(
                fields=["tenant_id", "application_no"],
                condition=models.Q(application_no__gt=""),
                name="uniq_hr_application_no_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "canonical_status"]),
            models.Index(fields=["tenant_id", "recruitment_position_id", "canonical_status"]),
            models.Index(fields=["tenant_id", "candidate_id"]),
            models.Index(fields=["tenant_id", "application_no"]),
            models.Index(fields=["tenant_id", "submitted_at"]),
            models.Index(fields=["tenant_id", "due_at"]),
        ]

    def __str__(self):
        return f"{self.application_no} [{self.canonical_status}]"


class HrApplicationTransition(models.Model):
    """状态迁移 ledger（§14.3）。每次 canonical_status 变化必须产生一条。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        HrJobApplication,
        on_delete=models.CASCADE,
        related_name="transitions",
        verbose_name=_("Application"),
    )
    from_status = models.CharField(max_length=24, choices=ApplicationCanonicalStatus.choices)
    to_status = models.CharField(max_length=24, choices=ApplicationCanonicalStatus.choices)
    action = models.CharField(max_length=64, blank=True, default="")
    reason_code = models.CharField(max_length=64, blank=True, default="")
    reason_text = models.TextField(blank=True, default="")
    actor_id = models.CharField(max_length=128, blank=True, default="")
    source = models.CharField(max_length=32, default="SYSTEM")
    occurred_at = models.DateTimeField(auto_now_add=True)
    correlation_id = models.CharField(max_length=128, blank=True, default="")
    workflow_stage_before = models.CharField(max_length=100, blank=True, default="")
    workflow_stage_after = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = _("Application Transition")
        verbose_name_plural = _("Application Transitions")
        indexes = [
            models.Index(fields=["tenant_id", "application_id", "occurred_at"]),
            models.Index(fields=["tenant_id", "to_status"]),
        ]

    def __str__(self):
        return f"{self.application_id} {self.from_status}→{self.to_status}"


class HrApplicationMaterial(models.Model):
    """申请材料（版本化 + SHA-256 + 核验 + 敏感级 + retention）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        HrJobApplication,
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name=_("Application"),
    )
    material_type = models.CharField(
        max_length=32, choices=MaterialType.choices, default=MaterialType.OTHER
    )
    title = models.CharField(max_length=250, blank=True, default="")
    version_no = models.PositiveIntegerField(default=1)
    file_name = models.CharField(max_length=250, blank=True, default="")
    file_path = models.CharField(max_length=500, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file_size_bytes = models.BigIntegerField(default=0)
    verification_status = models.CharField(
        max_length=16,
        choices=MaterialVerificationStatus.choices,
        default=MaterialVerificationStatus.PENDING,
    )
    sensitive_level = models.CharField(
        max_length=24, choices=SensitiveLevel.choices, default=SensitiveLevel.RESTRICTED_HR
    )
    reviewer_id = models.CharField(max_length=128, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    retention_until = models.DateField(null=True, blank=True)
    supersedes_id = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Application Material")
        verbose_name_plural = _("Application Materials")
        indexes = [
            models.Index(fields=["tenant_id", "application_id", "material_type"]),
            models.Index(fields=["tenant_id", "sha256"]),
        ]

    def __str__(self):
        return f"{self.application_id} {self.title or self.material_type} v{self.version_no}"


class HrApplicationSubmissionKey(models.Model):
    """提交幂等键记录（§49：同 Idempotency-Key 重放返回同一申请，绝不双提交）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    idempotency_key = models.CharField(max_length=128)
    application_id = models.ForeignKey(
        HrJobApplication,
        on_delete=models.CASCADE,
        related_name="submission_keys",
        verbose_name=_("Application"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Application Submission Key")
        verbose_name_plural = _("Application Submission Keys")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr_application_submission_key",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "idempotency_key"]),
        ]

    def __str__(self):
        return f"{self.idempotency_key} → {self.application_id}"
