"""
hr_onboarding/models/activation.py

正式生效（总册 §10.5-§10.7/§25）：
- HrActivationAttempt：ActivateOnboardingCase 领域命令执行记录（幂等键 + 状态 + 结果）；
- HrOnboardingActivationSnapshot：正式生效快照，审计可回答"当时按哪些来源数据创建"。
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import ActivationStatus


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _AppendOnlyActivationQuerySet(models.QuerySet):
    """Seal formal activation facts against instance-bypassing ORM writes."""

    immutable_code = "HR05_ACTIVATION_FACT_IMMUTABLE"

    def update(self, **kwargs):
        raise ValidationError(f"{self.immutable_code}: append a correction fact")

    def delete(self):
        raise ValidationError(f"{self.immutable_code}: formal facts cannot be deleted")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(f"{self.immutable_code}: append a correction fact")


class _AppendOnlyActivationManager(
    models.Manager.from_queryset(_AppendOnlyActivationQuerySet)
):
    def bulk_create(self, objs, *args, **kwargs):
        objects = list(objs)
        for obj in objects:
            obj._prepare_seal()
        return super().bulk_create(objects, *args, **kwargs)


class HrActivationAttempt(models.Model):
    """激活尝试（事务日志 + tenant-scoped 幂等）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="activation_attempts",
    )
    effective_at = models.DateField(null=True, blank=True)
    # Idempotency keys belong to a school boundary.  Global uniqueness made the
    # same client-generated key collide across unrelated tenants.
    idempotency_key = models.CharField(max_length=128)
    status = models.CharField(
        max_length=24,
        choices=ActivationStatus.choices,
        default=ActivationStatus.NOT_STARTED,
    )
    result_json = models.JSONField(default=dict, blank=True)
    snapshot_ref = models.UUIDField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Activation Attempt")
        verbose_name_plural = _("HR Activation Attempts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr05_activation_tenant_idem",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "status"]),
        ]

    def __str__(self):
        return f"{self.case_id}:{self.status}"


class HrOnboardingActivationSnapshot(models.Model):
    """正式生效初始事实（总册 §25）：一次成功激活一份，永久不可覆盖。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.OneToOneField(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.PROTECT,
        related_name="activation_snapshot",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    person_id = models.UUIDField(null=True, blank=True)
    staff_master_id = models.UUIDField(null=True, blank=True)
    employment_id = models.UUIDField(null=True, blank=True)
    assignment_id = models.UUIDField(null=True, blank=True)
    staff_no = models.CharField(max_length=64, blank=True, default="")
    organization_id = models.BigIntegerField(null=True, blank=True)
    position_id = models.BigIntegerField(null=True, blank=True)
    source_type = models.CharField(max_length=32, blank=True, default="")
    source_id = models.CharField(max_length=128, blank=True, default="")
    hr04_proposed_hire_id = models.CharField(max_length=128, blank=True, default="")
    hr04_application_id = models.CharField(max_length=128, blank=True, default="")
    source_versions_json = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyActivationManager()

    class Meta:
        verbose_name = _("HR Onboarding Activation Snapshot")
        verbose_name_plural = _("HR Onboarding Activation Snapshots")

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "caseId": str(self.case_id),
            "activatedAt": self.activated_at.isoformat() if self.activated_at else None,
            "personId": str(self.person_id) if self.person_id else None,
            "staffMasterId": str(self.staff_master_id) if self.staff_master_id else None,
            "employmentId": str(self.employment_id) if self.employment_id else None,
            "assignmentId": str(self.assignment_id) if self.assignment_id else None,
            "staffNo": self.staff_no or "",
            "organizationId": self.organization_id,
            "positionId": self.position_id,
            "sourceType": self.source_type or "",
            "sourceId": self.source_id or "",
            "hr04ProposedHireId": self.hr04_proposed_hire_id or "",
            "hr04ApplicationId": self.hr04_application_id or "",
            "sourceVersions": self.source_versions_json or {},
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def _prepare_seal(self) -> None:
        case = self.case
        if self.tenant_id != case.tenant_id:
            raise ValidationError("HR05_ACTIVATION_PARENT_TENANT_MISMATCH")
        parent_values = {
            "source_type": case.source_type or "",
            "source_id": case.source_id or "",
            "hr04_proposed_hire_id": case.hr04_proposed_hire_id or "",
            "hr04_application_id": case.hr04_application_id or "",
        }
        for field, parent_value in parent_values.items():
            current = getattr(self, field) or ""
            if current and current != parent_value:
                raise ValidationError(f"HR05_ACTIVATION_PARENT_CHAIN_MISMATCH:{field}")
            setattr(self, field, parent_value)
        if not self.activated_at:
            self.activated_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.activated_at
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValidationError("HR05_ACTIVATION_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "HR05_ACTIVATION_FACT_IMMUTABLE: append an activation amendment"
            )
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("HR05_ACTIVATION_FACT_IMMUTABLE: formal fact cannot be deleted")

    def __str__(self):
        return f"snapshot:{self.case_id}:{self.staff_no}"


class HrOnboardingActivationAmendment(models.Model):
    """Append-only correction/revocation chain for one activation fact."""

    class Action(models.TextChoices):
        CORRECTION = "CORRECTION", _("Correction")
        REVOCATION = "REVOCATION", _("Revocation")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    snapshot = models.ForeignKey(
        HrOnboardingActivationSnapshot,
        on_delete=models.PROTECT,
        related_name="amendments",
    )
    predecessor = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor",
    )
    sequence_no = models.PositiveIntegerField()
    action = models.CharField(max_length=16, choices=Action.choices)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    reason = models.TextField()
    before_snapshot_json = models.JSONField(default=dict)
    after_snapshot_json = models.JSONField(default=dict)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    effective_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _AppendOnlyActivationManager()

    class Meta:
        verbose_name = _("HR Onboarding Activation Amendment")
        verbose_name_plural = _("HR Onboarding Activation Amendments")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr05_act_amend_tenant_idem",
            ),
            models.UniqueConstraint(
                fields=["snapshot", "sequence_no"],
                name="uniq_hr05_act_amend_sequence",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_no__gt=0),
                name="ck_hr05_act_amend_sequence_pos",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "snapshot", "sequence_no"],
                name="idx_hr05_act_amend_chain",
            ),
        ]

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "snapshotId": str(self.snapshot_id),
            "predecessorId": str(self.predecessor_id) if self.predecessor_id else None,
            "sequenceNo": int(self.sequence_no),
            "action": self.action,
            "idempotencyKey": self.idempotency_key,
            "requestHash": self.request_hash,
            "reason": self.reason,
            "before": self.before_snapshot_json or {},
            "after": self.after_snapshot_json or {},
            "actorUserId": self.actor_user_id,
            "effectiveAt": self.effective_at.isoformat() if self.effective_at else None,
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def _prepare_seal(self) -> None:
        if not self.effective_at:
            self.effective_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.effective_at
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValidationError("HR05_ACTIVATION_AMENDMENT_HASH_MISMATCH")
        self.content_hash = expected

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "HR05_ACTIVATION_AMENDMENT_IMMUTABLE: append another amendment"
            )
        self._prepare_seal()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "HR05_ACTIVATION_AMENDMENT_IMMUTABLE: history cannot be deleted"
        )
