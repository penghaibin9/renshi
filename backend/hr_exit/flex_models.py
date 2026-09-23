"""HR16 owns flexible-retirement applications; HR17 is only a SELF adapter."""
import hashlib
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from horilla.hr_domain_models import HrTenantScopedModel


def canonical_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, cls=DjangoJSONEncoder).encode()).hexdigest()


class FlexAppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("FLEX_EVENT_IMMUTABLE")
    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("FLEX_EVENT_IMMUTABLE")
    def delete(self):
        raise ValueError("FLEX_EVENT_IMMUTABLE")


class FlexApplicationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("FLEX_USE_AUTHORITY_SERVICE")
    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("FLEX_USE_AUTHORITY_SERVICE")
    def delete(self):
        raise ValueError("FLEX_APPLICATION_DELETE_FORBIDDEN")


class RetirementFlexApplication(HrTenantScopedModel):
    class Mode(models.TextChoices):
        EARLY = "EARLY", "弹性提前退休"
        DELAY = "DELAY", "弹性延迟退休"
        END_DELAY = "END_DELAY", "协商终止弹性延迟"
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        SUBMITTED = "SUBMITTED", "待核验审批"
        RETURNED = "RETURNED", "退回补件"
        APPROVED = "APPROVED", "已批准，尚非退休事实"
        REJECTED = "REJECTED", "已驳回"
        CANCELLED = "CANCELLED", "已撤回"

    staff_id = models.UUIDField()
    person_id = models.UUIDField()
    employment_relationship_id = models.UUIDField()
    precheck_id = models.UUIDField()
    parent_application_id = models.UUIDField(null=True, blank=True)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    requested_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    version = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    notice_date = models.DateField(null=True, blank=True)
    notice_material_version_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=1000)
    authority_snapshot = models.JSONField(default=dict)
    review_snapshot = models.JSONField(default=dict)
    approved_by = models.PositiveBigIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_hash = models.CharField(max_length=64, blank=True, default="")
    exit_case_id = models.UUIDField(null=True, blank=True)

    objects = FlexApplicationQuerySet.as_manager()

    class Meta:
        db_table = "hr16_retirement_flex_application"
        permissions = [("hr.exit.flex.review", "核验与审批 HR16 弹性退休申请")]
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "staff_id", "idempotency_key"), name="uq_hr16_flex_self_command"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "employment_relationship_id", "status"), name="idx_hr16_flex_rel_status"),
            models.Index(fields=("tenant_id", "staff_id", "created_at"), name="idx_hr16_flex_self_time"),
            models.Index(fields=("tenant_id", "exit_case_id"), name="idx_hr16_flex_exit_case"),
        ]

    def approval_payload(self):
        return {"tenantId": self.tenant_id, "id": self.id, "staffId": self.staff_id,
            "personId": self.person_id, "relationshipId": self.employment_relationship_id,
            "precheckId": self.precheck_id, "parentId": self.parent_application_id,
            "mode": self.mode, "requestedDate": self.requested_date,
            "noticeDate": self.notice_date, "noticeVersionId": self.notice_material_version_id,
            "authority": self.authority_snapshot, "review": self.review_snapshot,
            "approvedBy": self.approved_by, "approvedAt": self.approved_at}

    def verify_seal(self):
        return bool(self.approved_at and self.approval_hash and self.approval_hash == canonical_hash(self.approval_payload()))

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old is not None:
            immutable = ("tenant_id", "staff_id", "person_id", "employment_relationship_id",
                "precheck_id", "parent_application_id", "mode", "requested_date", "created_by",
                "request_hash", "idempotency_key", "authority_snapshot")
            if any(getattr(old, name) != getattr(self, name) for name in immutable):
                raise ValueError("FLEX_IDENTITY_IMMUTABLE: withdraw and submit a new application")
            if old.approved_at and (self.status != self.Status.APPROVED or
                    canonical_hash(old.approval_payload()) != canonical_hash(self.approval_payload())):
                raise ValueError("FLEX_APPROVAL_IMMUTABLE: use an END_DELAY successor, never extend in place")
        if self.status == self.Status.APPROVED and not self.verify_seal():
            raise ValueError("FLEX_APPROVAL_SEAL_INVALID")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("FLEX_APPLICATION_DELETE_FORBIDDEN")


class RetirementFlexEvent(HrTenantScopedModel):
    application_id = models.UUIDField()
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    objects = FlexAppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = "hr16_retirement_flex_event"
        base_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "application_id", "version"), name="uq_hr16_flex_event_version")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("FLEX_EVENT_IMMUTABLE")
        if self.content_hash != canonical_hash(self.payload):
            raise ValueError("FLEX_EVENT_HASH_INVALID")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("FLEX_EVENT_IMMUTABLE")
