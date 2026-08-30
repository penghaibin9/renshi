"""
hr10_development/models/development_fact.py

发展事实 + 度量台账 + 合规规则 + 风险案例（总册 §111-122）。
"""

import hashlib
import json
import uuid

from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import FactType, RiskType, RiskCaseStatus, RiskSeverity
from hr10_development.models.base import DevelopmentTenantModel


def _development_fact_idempotency_key():
    return f"fact:{uuid.uuid4().hex}"


class DevelopmentFactQuerySet(models.QuerySet):
    """The formal HR10 record is append-only, including bulk ORM paths."""

    _MUTATION_ERROR = (
        "HR10_DEVELOPMENT_FACT_APPEND_ONLY: use DevelopmentFactAuthorityService"
    )

    def current(self):
        successor = self.model.objects.filter(
            tenant_id=OuterRef("tenant_id"), supersedes_fact_id=OuterRef("pk")
        )
        return self.annotate(_has_successor=Exists(successor)).filter(
            _has_successor=False
        )

    def effective(self):
        return self.current().exclude(record_kind="REVOCATION")

    def update(self, **kwargs):
        raise ValueError(self._MUTATION_ERROR)

    def delete(self):
        raise ValueError(self._MUTATION_ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._MUTATION_ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._MUTATION_ERROR)


class DevelopmentFactManager(models.Manager.from_queryset(DevelopmentFactQuerySet)):
    pass


class HrDevelopmentFact(DevelopmentTenantModel):
    class RecordKind(models.TextChoices):
        ORIGINAL = "ORIGINAL", _("原始正式事实")
        CORRECTION = "CORRECTION", _("追加更正")
        REVOCATION = "REVOCATION", _("追加撤销")

    staff_master_id = models.BigIntegerField(db_index=True)
    fact_type = models.CharField(max_length=32, choices=FactType.choices, db_index=True, verbose_name=_("事实类型"))
    source_case_type = models.CharField(max_length=64, verbose_name=_("来源 case 类型"))
    source_case_id = models.BigIntegerField()
    source_revision_no = models.IntegerField(default=0)
    activity_type = models.CharField(max_length=64, blank=True, default="")
    provider_org_id = models.BigIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    verified_hours = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    verified_days = models.IntegerField(null=True, blank=True)
    verified_credits = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    level_or_result = models.CharField(max_length=64, blank=True, default="")
    verification_status = models.CharField(max_length=48, db_index=True)
    evidence_package_hash = models.CharField(max_length=128, blank=True, default="")
    generated_at = models.DateTimeField()
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    supersedes_fact_id = models.BigIntegerField(null=True, blank=True)
    immutable_hash = models.CharField(max_length=128, blank=True, default="")
    record_kind = models.CharField(
        max_length=16, choices=RecordKind.choices, default=RecordKind.ORIGINAL,
        db_index=True,
    )
    correction_reason = models.CharField(max_length=128, blank=True, default="")
    correction_evidence_ref = models.CharField(max_length=256, blank=True, default="")
    idempotency_key = models.CharField(
        max_length=128, default=_development_fact_idempotency_key,
    )
    sealed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sealed_by = models.BigIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")

    objects = DevelopmentFactManager()

    _HASH_FIELDS = (
        "tenant_id", "staff_master_id", "fact_type", "source_case_type",
        "source_case_id", "source_revision_no", "activity_type", "provider_org_id",
        "start_date", "end_date", "verified_hours", "verified_days",
        "verified_credits", "level_or_result", "verification_status",
        "evidence_package_hash", "generated_at", "valid_from", "valid_to",
        "supersedes_fact_id", "record_kind", "correction_reason",
        "correction_evidence_ref", "idempotency_key", "sealed_at", "sealed_by",
    )

    class Meta:
        db_table = "hr_development_fact"
        verbose_name = _("发展事实")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "fact_type", "valid_from"])]
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr10_fact_one_successor",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr10_fact_idempotency",
            ),
            models.CheckConstraint(
                condition=(
                    Q(record_kind="ORIGINAL", supersedes_fact_id__isnull=True)
                    | (
                        Q(record_kind__in=("CORRECTION", "REVOCATION"))
                        & Q(supersedes_fact_id__isnull=False)
                        & ~Q(correction_reason="")
                        & ~Q(correction_evidence_ref="")
                    )
                ),
                name="ck_hr10_fact_lineage",
            ),
            models.CheckConstraint(
                condition=(
                    Q(sealed_at__isnull=False)
                    & ~Q(content_hash="")
                    & ~Q(immutable_hash="")
                ),
                name="ck_hr10_fact_sealed",
            ),
        ]

    @staticmethod
    def _canonical_value(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def calculate_content_hash(self) -> str:
        payload = {
            field: self._canonical_value(getattr(self, field))
            for field in self._HASH_FIELDS
        }
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def verify_content_hash(self) -> bool:
        return bool(self.sealed_at and self.content_hash) and (
            self.content_hash == self.calculate_content_hash()
        )

    def _validate_lineage(self):
        is_original = self.record_kind == self.RecordKind.ORIGINAL
        if is_original != (self.supersedes_fact_id is None):
            raise ValueError("HR10_DEVELOPMENT_FACT_LINEAGE_INVALID")
        if not is_original:
            if not self.correction_reason.strip() or not self.correction_evidence_ref.strip():
                raise ValueError("HR10_DEVELOPMENT_FACT_CORRECTION_EVIDENCE_REQUIRED")
            parent = type(self).objects.filter(
                pk=self.supersedes_fact_id, tenant_id=self.tenant_id
            ).first()
            if parent is None:
                raise ValueError("HR10_DEVELOPMENT_FACT_PARENT_NOT_IN_TENANT")
            if parent.staff_master_id != self.staff_master_id:
                raise ValueError("HR10_DEVELOPMENT_FACT_STAFF_CHAIN_MISMATCH")

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            raise ValueError("TENANT_CONTEXT_REQUIRED")
        if not self._state.adding:
            raise ValueError(
                "HR10_DEVELOPMENT_FACT_APPEND_ONLY: sealed facts cannot be updated"
            )
        self._validate_lineage()
        # Normalize values exactly as Django/MySQL will persist them so a value
        # supplied as an ISO string cannot produce a pre-save-only hash.
        for field_name in self._HASH_FIELDS:
            field = self._meta.get_field(field_name)
            setattr(self, field_name, field.to_python(getattr(self, field_name)))
        self.sealed_at = self.sealed_at or timezone.now()
        self.content_hash = self.calculate_content_hash()
        # Keep the historic public field aligned while consumers migrate.
        self.immutable_hash = self.content_hash
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "HR10_DEVELOPMENT_FACT_APPEND_ONLY: sealed facts cannot be deleted"
        )


class HrDevelopmentMetricLedger(DevelopmentTenantModel):
    staff_master_id = models.BigIntegerField(db_index=True)
    fact_id = models.BigIntegerField(db_index=True)
    metric_code = models.CharField(max_length=64, verbose_name=_("度量码"))
    raw_value = models.DecimalField(max_digits=10, decimal_places=2)
    raw_unit = models.CharField(max_length=16)
    normalized_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    normalized_unit = models.CharField(max_length=16, blank=True, default="")
    conversion_rule_version = models.CharField(max_length=64, blank=True, default="")
    eligibility_rule_version = models.CharField(max_length=64, blank=True, default="")
    window_key = models.CharField(max_length=64, blank=True, default="")
    calculated_at = models.DateTimeField()

    class Meta:
        db_table = "hr_development_metric_ledger"
        verbose_name = _("发展度量台账")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "metric_code", "window_key"])]


class HrDevelopmentComplianceRule(DevelopmentTenantModel):
    rule_pack_id = models.CharField(max_length=128, verbose_name=_("规则包 ID"))
    version = models.IntegerField(default=1)
    population_rule_json = models.JSONField(default=dict)
    metric_code = models.CharField(max_length=64)
    time_window_type = models.CharField(max_length=32)
    minimum_value = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=16)
    eligible_activity_types = models.JSONField(default=list)
    minimum_trust_level = models.IntegerField(default=3)
    exception_policy_json = models.JSONField(blank=True, default=dict)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="PUBLISHED", verbose_name=_("状态"))

    class Meta:
        db_table = "hr_development_compliance_rule"
        verbose_name = _("合规规则")
        verbose_name_plural = verbose_name
        unique_together = [("tenant_id", "rule_pack_id", "version")]


class HrDevelopmentRiskCase(DevelopmentTenantModel):
    risk_type = models.CharField(max_length=48, choices=RiskType.choices, db_index=True, verbose_name=_("风险类型"))
    staff_master_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    source_case_type = models.CharField(max_length=64, blank=True, default="")
    source_case_id = models.BigIntegerField(null=True, blank=True)
    severity = models.CharField(max_length=16, choices=RiskSeverity.choices, default=RiskSeverity.MEDIUM)
    status = models.CharField(max_length=32, choices=RiskCaseStatus.choices, default=RiskCaseStatus.OPEN, db_index=True)
    detected_rule_version = models.CharField(max_length=64, blank=True, default="")
    detected_at = models.DateTimeField()
    owner_id = models.BigIntegerField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.TextField(blank=True, default="")
    resolution_evidence_refs = models.JSONField(blank=True, default=list)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_development_risk_case"
        verbose_name = _("发展风险案例")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["tenant_id", "risk_type", "status", "due_at"])]
