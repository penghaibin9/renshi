"""HR13 title evaluation authority models.

The first slice intentionally owns only three facts:
- frozen policy versions,
- title application cases,
- effective title result facts.

Expert reviews, evidence, publicity and appeal tables will attach to these
roots; they must not replace them or write HR03/HR14/HR15 authority directly.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel, HrVersionedModel


class TitlePolicyVersion(HrVersionedModel):
    policy_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    title_series_code = models.CharField(max_length=64, blank=True, default="")
    title_level_code = models.CharField(max_length=64, blank=True, default="")
    track_code = models.CharField(max_length=64, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr13_title_policy_version"
        permissions = [("hr.title.view", "查看 HR13 职称评审工作区")]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "policy_code", "version_no"),
                name="uq_hr13_policy_tenant_code_ver",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr13_policy_effective_range",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "status"), name="idx_hr13_policy_tenant_status"),
        ]


class TitleApplicationCase(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        RETURNED = "RETURNED", "Returned for correction"
        ELIGIBLE = "ELIGIBLE", "Eligibility passed"
        REJECTED = "REJECTED", "Rejected"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        PROPOSED = "PROPOSED", "Proposed result"
        PUBLICITY = "PUBLICITY", "Publicity"
        EFFECTIVE = "EFFECTIVE", "Effective"
        REVOKED = "REVOKED", "Revoked"

    case_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    policy_version_id = models.UUIDField()
    batch_no = models.CharField(max_length=64)
    requested_title_code = models.CharField(max_length=64)
    requested_title_name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr13_title_application_case"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr13_case_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr13_case_tenant_person"),
            models.Index(fields=("tenant_id", "batch_no", "status"), name="idx_hr13_case_tenant_batch"),
        ]


class ProfessionalTitleResult(HrTenantScopedModel):
    class Status(models.TextChoices):
        EFFECTIVE = "EFFECTIVE", "Effective"
        REVISED = "REVISED", "Revised"
        REVOKED = "REVOKED", "Revoked"

    result_no = models.CharField(max_length=64)
    person_id = models.UUIDField()
    application_case_id = models.UUIDField()
    title_code = models.CharField(max_length=64)
    title_name = models.CharField(max_length=200)
    title_series_code = models.CharField(max_length=64, blank=True, default="")
    title_level_code = models.CharField(max_length=64, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.EFFECTIVE, db_index=True)
    supersedes_result_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr13_professional_title_result"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "result_no"), name="uq_hr13_result_tenant_no"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr13_result_effective_range",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "person_id", "status"), name="idx_hr13_result_tenant_person"),
        ]
