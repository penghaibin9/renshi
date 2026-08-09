"""
hr_external/models/renewal_exit.py —— 续聘与退出（S8，总册 §58-70）。

- HrExternalRenewalReview：到期评估（§59/§60），决策 RENEW/RENEW_WITH_CHANGES/CHANGE_CATEGORY/
  CHANGE_HOST_ORG/CONVERT_TO_REGULAR_HR_PROCESS/DO_NOT_RENEW/NEEDS_REVIEW；
- 续聘不是改 end_at（§61/§138.11）：决策 RENEW → 创建新 Engagement（下一轮 S5 流程）；
- HrExternalExitCase：退出（§63/§64/§65），权限回收闭环（§66/§138.12）；
- 历史任务/成果/评价/协议保留（§70/§138.15）；退出不是 is_active=False。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ExitReason,
    ExitStatus,
    RenewalDecision,
    RenewalReviewStatus,
)


class HrExternalRenewalReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="renewal_reviews",
    )
    review_due_at = models.DateField()
    task_completion_summary = models.TextField(blank=True, default="")
    quality_summary = models.TextField(blank=True, default="")
    agreement_status = models.CharField(max_length=32, blank=True, default="")
    access_summary = models.TextField(blank=True, default="")
    requester_org_opinion = models.TextField(blank=True, default="")
    person_willingness = models.TextField(blank=True, default="")
    decision = models.CharField(
        max_length=32,
        choices=RenewalDecision.choices,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=16,
        choices=RenewalReviewStatus.choices,
        default=RenewalReviewStatus.DRAFT,
    )
    decided_by = models.BigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    next_engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="renewed_from",
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Renewal Review")
        verbose_name_plural = _("HR External Renewal Reviews")
        constraints = [
            models.UniqueConstraint(
                fields=["engagement_id", "review_due_at"],
                name="uniq_hr_external_renewal_per_cycle",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_renewal_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status", "review_due_at"],
                name="hr_external_renewal_status_due_idx",
            ),
            models.Index(
                fields=["tenant_id", "engagement_id"],
                name="hr_external_renewal_eng_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] renewal {self.status}"


class HrExternalExitCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="exit_cases",
    )
    exit_reason = models.CharField(
        max_length=32,
        choices=ExitReason.choices,
        default=ExitReason.TERM_COMPLETED,
    )
    planned_end_at = models.DateField(null=True, blank=True)
    actual_end_at = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ExitStatus.choices,
        default=ExitStatus.PLANNED,
        db_index=True,
    )
    required_clearance_policy = models.CharField(max_length=64, blank=True, default="")
    agreement_termination_ref = models.CharField(max_length=64, blank=True, default="")
    clearance_items = models.JSONField(default=list, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Exit Case")
        verbose_name_plural = _("HR External Exit Cases")
        constraints = [
            # 一个 engagement 最多一个 active exit case（§118）
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_id"],
                condition=models.Q(status__in=["PLANNED", "UNDER_REVIEW", "READY_TO_EXIT", "EXITING", "CLEARANCE_PENDING"]),
                name="uniq_hr_external_active_exit_per_eng",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_exit_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hr_external_exit_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "engagement_id"],
                name="hr_external_exit_eng_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] exit {self.status}"
