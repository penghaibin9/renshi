"""School-approved payroll configuration and append-only calculation evidence.

These models extend HR15. Official wage results remain PayrollResultFact and
continue through the existing review/finalization/payment authority services.
"""
from django.db import models
from django.db.models import Q
from horilla.hr_domain_models import HrTenantScopedModel


class ConfigurationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "status" in kwargs or self.exclude(status="DRAFT").exists():
            raise ValueError("PAYROLL_CONFIGURATION_SEALED: use a reviewed new version")
        return super().update(**kwargs)

    def delete(self):
        if self.exclude(status="DRAFT").exists():
            raise ValueError("PAYROLL_CONFIGURATION_SEALED")
        return super().delete()

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError("PAYROLL_CONFIGURATION_BULK_MUTATION_FORBIDDEN")

    def bulk_create(self, objs, **kwargs):
        raise ValueError("PAYROLL_CONFIGURATION_USE_REVIEW_SERVICE")


class ApprovedConfiguration(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "待复核"
        PUBLISHED = "PUBLISHED", "已生效配置"
        RETIRED = "RETIRED", "已被替代"

    version_no = models.PositiveIntegerField(default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    evidence_ref = models.CharField(max_length=500)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    published_by = models.PositiveBigIntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    supersedes_id = models.UUIDField(null=True, blank=True)
    objects = ConfigurationQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        old = type(self)._base_manager.filter(pk=self.pk).values().first() if self.pk else None
        if old and old["status"] in {"PUBLISHED", "RETIRED"}:
            mutable = {"updated_at", "updated_by", "status"}
            changed = [field.attname for field in self._meta.concrete_fields
                       if field.attname not in mutable and old[field.attname] != getattr(self, field.attname)]
            if changed or (self.status != old["status"] and not (old["status"] == "PUBLISHED" and self.status == "RETIRED")):
                raise ValueError("PAYROLL_CONFIGURATION_SEALED: " + ",".join(changed))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValueError("PAYROLL_CONFIGURATION_SEALED")
        return super().delete(*args, **kwargs)


class PayrollPolicyVersion(ApprovedConfiguration):
    pay_group_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    configuration_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "hr15_policy_version"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "pay_group_code", "version_no"), name="uq_hr15_policy_group_version"),
                       models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_policy_dates")]


class PayrollStandardVersion(ApprovedConfiguration):
    pay_group_code = models.CharField(max_length=64)
    table_code = models.CharField(max_length=64)
    level_code = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency_code = models.CharField(max_length=3, default="CNY")

    class Meta:
        db_table = "hr15_standard_version"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "pay_group_code", "table_code", "level_code", "version_no"), name="uq_hr15_standard_version"),
                       models.CheckConstraint(condition=Q(amount__gte=0), name="ck_hr15_standard_amount"),
                       models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_standard_dates")]


class PayrollBasisVersion(ApprovedConfiguration):
    payroll_profile_id = models.UUIDField()
    staff_id = models.UUIDField()
    selectors_json = models.JSONField(default=dict, blank=True)
    variables_json = models.JSONField(default=dict, blank=True)
    tax_deductions_json = models.JSONField(default=dict, blank=True)
    cost_shares_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "hr15_basis_version"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "payroll_profile_id", "version_no"), name="uq_hr15_basis_version"),
                       models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_basis_dates")]


class PayrollWorkloadFact(ApprovedConfiguration):
    payroll_period_id = models.UUIDField()
    staff_id = models.UUIDField()
    workload_key = models.CharField(max_length=128)
    variable_key = models.CharField(max_length=64)
    units = models.DecimalField(max_digits=14, decimal_places=4)
    share = models.DecimalField(max_digits=9, decimal_places=6)
    coefficient = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        db_table = "hr15_verified_workload"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "payroll_period_id", "workload_key", "staff_id", "version_no"), name="uq_hr15_workload_source"),
                       models.CheckConstraint(condition=Q(units__gte=0) & Q(share__gt=0) & Q(share__lte=1) & Q(coefficient__gte=0), name="ck_hr15_workload_values")]


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("PAYROLL_EVIDENCE_APPEND_ONLY")
    def delete(self):
        raise ValueError("PAYROLL_EVIDENCE_APPEND_ONLY")
    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError("PAYROLL_EVIDENCE_APPEND_ONLY")
    def bulk_create(self, objs, **kwargs):
        raise ValueError("PAYROLL_EVIDENCE_USE_SERVICE")


class AppendOnlyEvidence(HrTenantScopedModel):
    objects = ImmutableQuerySet.as_manager()
    class Meta:
        abstract = True
    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_EVIDENCE_APPEND_ONLY")
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValueError("PAYROLL_EVIDENCE_APPEND_ONLY")


class PayrollTrial(AppendOnlyEvidence):
    payroll_period_id = models.UUIDField()
    staff_id = models.UUIDField()
    revision_no = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=128)
    purpose = models.CharField(max_length=16, default="NORMAL")
    source_result_id = models.UUIDField(null=True, blank=True)
    input_payload_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "hr15_trial_revision"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "payroll_period_id", "staff_id", "revision_no"), name="uq_hr15_trial_revision"),
                       models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uq_hr15_trial_idempotency")]


class PayrollTrialApproval(AppendOnlyEvidence):
    trial_id = models.UUIDField()
    trial_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=16)
    note = models.CharField(max_length=1000)

    class Meta:
        db_table = "hr15_trial_approval"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "trial_id"), name="uq_hr15_trial_approval")]


class PayrollTaxAccount(HrTenantScopedModel):
    withholding_agent_code = models.CharField(max_length=64)
    person_id = models.UUIDField()
    tax_year = models.PositiveIntegerField()
    version_no = models.PositiveIntegerField(default=0)
    totals_json = models.JSONField(default=dict, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    pending_result_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr15_tax_account"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "withholding_agent_code", "person_id", "tax_year"), name="uq_hr15_tax_person_year")]


class PayrollTaxReservation(HrTenantScopedModel):
    payroll_result_id = models.UUIDField()
    tax_account_id = models.UUIDField()
    staff_id = models.UUIDField()
    input_json = models.JSONField(default=dict, blank=True)
    quote_json = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="RESERVED")
    receipt_ref = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "hr15_tax_reservation"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "payroll_result_id"), name="uq_hr15_tax_result")]

    def save(self, *args, **kwargs):
        old = type(self)._base_manager.filter(pk=self.pk).values().first() if self.pk else None
        if old:
            for name in ("tenant_id", "payroll_result_id", "tax_account_id", "staff_id", "input_json", "quote_json", "content_hash"):
                if old[name] != getattr(self, name):
                    raise ValueError("PAYROLL_TAX_EVIDENCE_IMMUTABLE")
            if old["status"] in {"POSTED", "VOIDED"} and (self.status != old["status"] or self.receipt_ref != old["receipt_ref"]):
                raise ValueError("PAYROLL_TAX_TERMINAL_IMMUTABLE")
        return super().save(*args, **kwargs)


class PayrollImportStage(HrTenantScopedModel):
    kind = models.CharField(max_length=16, default="STANDARD")
    file_hash = models.CharField(max_length=64)
    stage_hash = models.CharField(max_length=64)
    rows_json = models.JSONField(default=list, blank=True)
    errors_json = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, default="PREVIEW")
    applied_ids_json = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_policy_import_stage"


class PayrollRetroApplication(AppendOnlyEvidence):
    source_result_id = models.UUIDField()
    trial_id = models.UUIDField()
    adjustment_result_id = models.UUIDField()
    prior_chain_hash = models.CharField(max_length=64)
    delta_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "hr15_retro_application"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "trial_id"), name="uq_hr15_retro_trial")]


class PayrollPolicyScope(HrTenantScopedModel):
    """Stable rows serialize configuration publication, including initially empty scopes."""
    scope_key = models.CharField(max_length=128)
    class Meta:
        db_table = "hr15_policy_scope_lock"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "scope_key"), name="uq_hr15_policy_scope")]


class PayrollTaxReceiptSupplement(AppendOnlyEvidence):
    """Additional authenticated bank proof; the original terminal receipt is never edited."""
    tax_reservation_id = models.UUIDField()
    receipt_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    class Meta:
        db_table = "hr15_tax_receipt_supplement"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "tax_reservation_id"), name="uq_hr15_tax_receipt_supplement")]
