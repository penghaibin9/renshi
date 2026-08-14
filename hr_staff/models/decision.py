"""HR03 formal personnel decision and reward/disciplinary authorities."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class HrPersonnelDecision(models.Model):
    """Immutable EFFECTIVE personnel decision fact.

    Corrections and revocations append a new decision that references the prior
    fact through ``supersedes_decision_id``. Existing effective rows are never
    overwritten in place.
    """

    class DecisionType(models.TextChoices):
        APPOINTMENT = "APPOINTMENT", _("Appointment")
        TRANSFER = "TRANSFER", _("Transfer")
        PROMOTION = "PROMOTION", _("Promotion")
        DEMOTION = "DEMOTION", _("Demotion")
        STATUS = "STATUS", _("Status")
        REWARD = "REWARD", _("Reward")
        DISCIPLINE = "DISCIPLINE", _("Discipline")
        OTHER = "OTHER", _("Other")

    class DecisionAction(models.TextChoices):
        ISSUE = "ISSUE", _("Issue")
        CORRECT = "CORRECT", _("Correct")
        REVOKE = "REVOKE", _("Revoke")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    decision_no = models.CharField(max_length=64)
    staff = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        related_name="personnel_decisions",
    )
    decision_type = models.CharField(max_length=24, choices=DecisionType.choices)
    decision_action = models.CharField(
        max_length=16, choices=DecisionAction.choices, default=DecisionAction.ISSUE
    )
    title = models.CharField(max_length=200)
    basis_text = models.TextField(blank=True, default="")
    content_snapshot_json = models.JSONField(default=dict)
    decided_at = models.DateTimeField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    supersedes_decision_id = models.UUIDField(null=True, blank=True)
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    created_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Personnel Decision")
        verbose_name_plural = _("HR Personnel Decisions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "decision_no"], name="uq_hr03_dec_tenant_no"
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "supersedes_decision_id"],
                name="uq_hr03_dec_supersede",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr03_dec_date_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "staff", "effective_from"],
                name="idx_hr03_dec_staff_eff",
            ),
            models.Index(
                fields=["tenant_id", "source_business_type", "source_business_id"],
                name="idx_hr03_dec_source",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HrPersonnelDecision is immutable; append a new decision fact")
        return super().save(*args, **kwargs)


class HrRewardDisciplinaryCase(models.Model):
    """Workflow case whose EFFECTIVE terminal state points at a formal decision."""

    class Kind(models.TextChoices):
        REWARD = "REWARD", _("Reward")
        DISCIPLINE = "DISCIPLINE", _("Discipline")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        RETURNED = "RETURNED", _("Returned")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        EFFECTIVE = "EFFECTIVE", _("Effective")
        CANCELLED = "CANCELLED", _("Cancelled")

    TERMINAL_STATUSES = frozenset(
        {Status.REJECTED, Status.EFFECTIVE, Status.CANCELLED}
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=64)
    staff = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        related_name="reward_disciplinary_cases",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    category_code = models.CharField(max_length=64)
    level_code = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=200)
    reason_text = models.TextField(blank=True, default="")
    occurred_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    decision = models.ForeignKey(
        HrPersonnelDecision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reward_disciplinary_cases",
    )
    final_snapshot_json = models.JSONField(default=dict, blank=True)
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    created_by = models.BigIntegerField(null=True, blank=True)
    updated_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Reward / Disciplinary Case")
        verbose_name_plural = _("HR Reward / Disciplinary Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"], name="uq_hr03_rdc_tenant_no"
            ),
            models.CheckConstraint(
                condition=~Q(status="EFFECTIVE") | Q(decision__isnull=False),
                name="ck_hr03_rdc_eff_dec",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "staff", "status"],
                name="idx_hr03_rdc_staff_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            persisted = type(self).objects.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            if persisted in self.TERMINAL_STATUSES:
                raise ValueError(
                    "terminal reward/disciplinary case is immutable; append a new fact"
                )
        return super().save(*args, **kwargs)
