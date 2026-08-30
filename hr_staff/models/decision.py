"""HR03 formal personnel decision and reward/disciplinary authorities."""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PersonnelDecisionQuerySet(models.QuerySet):
    """Formal personnel decisions are append-only through every ORM path."""

    _ERROR = "HR03_PERSONNEL_DECISION_APPEND_ONLY: append a successor fact"

    def current(self):
        successor = self.model.objects.filter(
            tenant_id=OuterRef("tenant_id"),
            supersedes_decision_id=OuterRef("pk"),
        )
        return self.annotate(_has_successor=Exists(successor)).filter(
            _has_successor=False
        )

    def effective(self):
        return self.current().exclude(
            decision_action=HrPersonnelDecision.DecisionAction.REVOKE
        )

    def effective_as_of(self, as_of):
        """Resolve the chain tip that was business-effective on ``as_of``."""
        successor = self.model.objects.filter(
            tenant_id=OuterRef("tenant_id"),
            supersedes_decision_id=OuterRef("pk"),
            effective_from__lte=as_of,
        )
        return (
            self.filter(effective_from__lte=as_of)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .annotate(_has_effective_successor=Exists(successor))
            .filter(_has_effective_successor=False)
            .exclude(decision_action=HrPersonnelDecision.DecisionAction.REVOKE)
        )

    def update(self, **kwargs):
        raise ValueError(self._ERROR)

    def delete(self):
        raise ValueError(self._ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._ERROR)


class PersonnelDecisionManager(models.Manager.from_queryset(PersonnelDecisionQuerySet)):
    pass


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
    correction_reason = models.CharField(max_length=256, blank=True, default="")
    correction_evidence_ref = models.CharField(max_length=256, blank=True, default="")
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    created_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sealed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")

    objects = PersonnelDecisionManager()

    _HASH_FIELDS = (
        "tenant_id",
        "decision_no",
        "staff_id",
        "decision_type",
        "decision_action",
        "title",
        "basis_text",
        "content_snapshot_json",
        "decided_at",
        "effective_from",
        "effective_to",
        "supersedes_decision_id",
        "correction_reason",
        "correction_evidence_ref",
        "source_business_type",
        "source_business_id",
        "correlation_id",
        "created_by",
        "sealed_at",
    )

    class Meta:
        verbose_name = _("HR Personnel Decision")
        verbose_name_plural = _("HR Personnel Decisions")
        base_manager_name = "objects"
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
            models.CheckConstraint(
                condition=(
                    Q(
                        decision_action="ISSUE",
                        supersedes_decision_id__isnull=True,
                        correction_reason="",
                        correction_evidence_ref="",
                    )
                    | (
                        Q(decision_action__in=("CORRECT", "REVOKE"))
                        & Q(supersedes_decision_id__isnull=False)
                        & ~Q(correction_reason="")
                        & ~Q(correction_evidence_ref="")
                    )
                ),
                name="ck_hr03_dec_lineage",
            ),
            models.CheckConstraint(
                condition=Q(sealed_at__isnull=False) & ~Q(content_hash=""),
                name="ck_hr03_dec_sealed",
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

    @staticmethod
    def _canonical_value(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    def calculate_content_hash(self) -> str:
        payload = {
            field: self._canonical_value(getattr(self, field))
            for field in self._HASH_FIELDS
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify_content_hash(self) -> bool:
        return bool(self.sealed_at and self.content_hash) and (
            self.content_hash == self.calculate_content_hash()
        )

    def _validate_lineage(self):
        if not self.tenant_id:
            raise ValueError("TENANT_CONTEXT_REQUIRED")
        if not self.staff_id:
            raise ValueError("HR03_PERSONNEL_DECISION_STAFF_REQUIRED")
        staff_tenant = self.staff.tenant_id
        if staff_tenant != self.tenant_id:
            raise ValueError("HR03_PERSONNEL_DECISION_STAFF_TENANT_MISMATCH")
        if self.decision_action == self.DecisionAction.ISSUE:
            if self.supersedes_decision_id:
                raise ValueError("HR03_PERSONNEL_DECISION_LINEAGE_INVALID")
            if self.correction_reason or self.correction_evidence_ref:
                raise ValueError("HR03_PERSONNEL_DECISION_LINEAGE_INVALID")
            return
        if self.decision_action not in {
            self.DecisionAction.CORRECT,
            self.DecisionAction.REVOKE,
        }:
            raise ValueError("HR03_PERSONNEL_DECISION_ACTION_INVALID")
        if not self.supersedes_decision_id:
            raise ValueError("HR03_PERSONNEL_DECISION_PARENT_REQUIRED")
        if not self.correction_reason.strip() or not self.correction_evidence_ref.strip():
            raise ValueError("HR03_PERSONNEL_DECISION_CORRECTION_EVIDENCE_REQUIRED")
        parent = type(self).objects.filter(
            pk=self.supersedes_decision_id,
            tenant_id=self.tenant_id,
        ).first()
        if parent is None:
            raise ValueError("HR03_PERSONNEL_DECISION_PARENT_NOT_IN_TENANT")
        if parent.staff_id != self.staff_id:
            raise ValueError("HR03_PERSONNEL_DECISION_STAFF_CHAIN_MISMATCH")
        if parent.decision_type != self.decision_type:
            raise ValueError("HR03_PERSONNEL_DECISION_TYPE_CHAIN_MISMATCH")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HrPersonnelDecision is immutable; append a new decision fact")
        self._validate_lineage()
        for field_name in self._HASH_FIELDS:
            field = self._meta.get_field(field_name)
            setattr(self, field_name, field.to_python(getattr(self, field_name)))
        self.sealed_at = self.sealed_at or timezone.now()
        self.content_hash = self.calculate_content_hash()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR03_PERSONNEL_DECISION_APPEND_ONLY: delete forbidden")


class RewardDisciplinaryCaseQuerySet(models.QuerySet):
    """Terminal workflow rows cannot be rewritten through bulk ORM paths."""

    _ERROR = "HR03_REWARD_DISCIPLINARY_TERMINAL_APPEND_ONLY"
    _AUTHORITY_FIELDS = {"status", "decision", "decision_id", "final_snapshot_json"}

    def _assert_no_terminal(self):
        if self.filter(
            status__in=HrRewardDisciplinaryCase.TERMINAL_STATUSES
        ).exists():
            raise ValueError(self._ERROR)

    def update(self, **kwargs):
        self._assert_no_terminal()
        if self._AUTHORITY_FIELDS.intersection(kwargs):
            raise ValueError(self._ERROR)
        return super().update(**kwargs)

    def delete(self):
        self._assert_no_terminal()
        return super().delete()

    def bulk_create(self, objs, **kwargs):
        if any(
            obj.status in HrRewardDisciplinaryCase.TERMINAL_STATUSES
            or obj.decision_id
            for obj in objs
        ):
            raise ValueError(self._ERROR)
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if self._AUTHORITY_FIELDS.intersection(fields) or any(
            obj.status in HrRewardDisciplinaryCase.TERMINAL_STATUSES for obj in objs
        ):
            raise ValueError(self._ERROR)
        return super().bulk_update(objs, fields, **kwargs)


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

    objects = RewardDisciplinaryCaseQuerySet.as_manager()

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
        if self._state.adding:
            if self.status in self.TERMINAL_STATUSES or self.decision_id:
                raise ValueError("HR03_REWARD_DISCIPLINARY_SERVICE_REQUIRED")
        else:
            persisted = type(self).objects.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            if persisted in self.TERMINAL_STATUSES:
                raise ValueError(
                    "terminal reward/disciplinary case is immutable; append a new fact"
                )
            if (
                self.status in self.TERMINAL_STATUSES
                and not getattr(self, "_allow_terminal_transition", False)
            ):
                raise ValueError("HR03_REWARD_DISCIPLINARY_SERVICE_REQUIRED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in self.TERMINAL_STATUSES:
            raise ValueError("HR03_REWARD_DISCIPLINARY_TERMINAL_APPEND_ONLY")
        return super().delete(*args, **kwargs)
