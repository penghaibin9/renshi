"""Immutable HR18 observation receipts; not another personnel authority."""
import hashlib
import json
from django.db import models
from horilla.hr_domain_models import HrTenantScopedModel

class SnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("OBSERVATION_IMMUTABLE")
    def bulk_update(self, *args, **kwargs):
        raise ValueError("OBSERVATION_IMMUTABLE")
    def delete(self):
        raise ValueError("OBSERVATION_DELETE_FORBIDDEN")

class OperationalSnapshot(HrTenantScopedModel):
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    catalog_version = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    evidence_hash = models.CharField(max_length=64)
    objects = SnapshotQuerySet.as_manager()

    class Meta:
        db_table = "hr18_operational_snapshot"
        permissions = [("hr.data.snapshot.capture", "冻结学校全域人事运行观察快照")]
        constraints = [models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uq_hr18_observation_command")]
        indexes = [models.Index(fields=("tenant_id", "created_at"), name="idx_hr18_observation_time")]

    def compute_hash(self):
        return hashlib.sha256(json.dumps({"tenantId": self.tenant_id, "catalogVersion": self.catalog_version,
            "payload": self.payload}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("OBSERVATION_IMMUTABLE")
        if self.evidence_hash != self.compute_hash():
            raise ValueError("OBSERVATION_HASH_MISMATCH")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("OBSERVATION_DELETE_FORBIDDEN")
