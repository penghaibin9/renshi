"""Durable evidence for the HR15 legacy-payroll cutover boundary."""

from __future__ import annotations

from django.db import models

from horilla.hr_domain_models import HrTenantScopedModel


class LegacyPayrollAssetInventory(HrTenantScopedModel):
    class Status(models.TextChoices):
        COMPLETE = "COMPLETE", "Complete"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    inventory_no = models.CharField(max_length=96)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    legacy_row_count = models.PositiveIntegerField(default=0)
    matched_row_count = models.PositiveIntegerField(default=0)
    unavailable_row_count = models.PositiveIntegerField(default=0)
    snapshot_hash = models.CharField(max_length=64)
    reason_codes_json = models.JSONField(default=list, blank=True)
    captured_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_legacy_payroll_inventory"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "inventory_no"),
                name="uq_hr15_legacy_inventory_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "captured_at"),
                name="idx_hr15_leg_inv_state",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("LEGACY_PAYROLL_INVENTORY_IMMUTABLE")
        return super().save(*args, **kwargs)


class LegacyPayrollMappingFact(HrTenantScopedModel):
    inventory_id = models.UUIDField()
    legacy_payslip_id = models.PositiveBigIntegerField()
    legacy_employee_ref_hash = models.CharField(max_length=64)
    staff_id = models.UUIDField(null=True, blank=True)
    payroll_period_id = models.UUIDField(null=True, blank=True)
    payroll_result_id = models.UUIDField(null=True, blank=True)
    payroll_payslip_id = models.UUIDField(null=True, blank=True)
    finance_reconciliation_id = models.UUIDField(null=True, blank=True)
    reconciliation_status = models.CharField(max_length=48, db_index=True)
    legacy_amount_hash = models.CharField(max_length=64, blank=True, default="")
    authority_amount_hash = models.CharField(max_length=64, blank=True, default="")
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "hr15_legacy_payroll_mapping_fact"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "inventory_id", "legacy_payslip_id"),
                name="uq_hr15_legacy_mapping_row",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "inventory_id", "reconciliation_status"),
                name="idx_hr15_legacy_mapping_state",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("LEGACY_PAYROLL_MAPPING_IMMUTABLE")
        return super().save(*args, **kwargs)


class LegacyPayrollCutoverControl(HrTenantScopedModel):
    class Status(models.TextChoices):
        INVENTORIED = "INVENTORIED", "Inventoried"
        VERIFIED = "VERIFIED", "Verified"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        ACTIVE = "ACTIVE", "Active"

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.INVENTORIED, db_index=True
    )
    latest_inventory_id = models.UUIDField(null=True, blank=True)
    latest_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    activation_key = models.CharField(max_length=96, blank=True, default="")
    activation_evidence_hash = models.CharField(max_length=64, blank=True, default="")
    activation_evidence_json = models.JSONField(default=dict, blank=True)
    write_block_enabled = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "hr15_legacy_payroll_cutover"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id",), name="uq_hr15_legacy_cutover_tenant"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                "status",
                "latest_inventory_id",
                "latest_snapshot_hash",
                "activation_key",
                "activation_evidence_hash",
                "activation_evidence_json",
                "write_block_enabled",
                "activated_at",
                "activated_by",
            ).first()
            if persisted and persisted["status"] == self.Status.ACTIVE:
                changed = [
                    field for field, value in persisted.items() if getattr(self, field) != value
                ]
                if changed:
                    raise ValueError("LEGACY_PAYROLL_CUTOVER_IMMUTABLE")
        return super().save(*args, **kwargs)


class LegacyPayrollWriteBlockAudit(HrTenantScopedModel):
    cutover_id = models.UUIDField()
    operation = models.CharField(max_length=24)
    object_ref_hash = models.CharField(max_length=64, blank=True, default="")
    actor_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    reason_code = models.CharField(max_length=64)
    blocked_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_legacy_payroll_write_block_audit"
        indexes = [
            models.Index(
                fields=("tenant_id", "blocked_at"), name="idx_hr15_legacy_write_block"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("LEGACY_PAYROLL_WRITE_BLOCK_AUDIT_IMMUTABLE")
        return super().save(*args, **kwargs)


class HrPayrollLegacyTakeoverPermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.payroll.legacy_takeover.view", "HR15: View legacy payroll takeover evidence"),
            ("hr.payroll.legacy_takeover.manage", "HR15: Verify and activate legacy payroll takeover"),
        )
