"""HR13 title evaluation authority models.

HR13 owns the frozen evaluation policy, application workflow, evidence snapshots
used by the review, qualification decisions, and formal title result history.
Upstream HR03/09/10/12 facts are referenced through provider metadata and copied
only as review-time snapshots; HR13 never becomes their source of truth.
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
        permissions = [
            ("hr.title.view", "查看 HR13 职称评审工作区"),
            ("hr.title.review", "执行 HR13 资格审查"),
        ]
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


class TitleQualificationDecision(HrTenantScopedModel):
    """Append-only eligibility-review decision for one submission attempt."""

    class Decision(models.TextChoices):
        ELIGIBLE = "ELIGIBLE", "Eligible"
        RETURNED = "RETURNED", "Returned for correction"
        REJECTED = "REJECTED", "Rejected"

    decision_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    attempt_no = models.PositiveIntegerField()
    decision = models.CharField(max_length=16, choices=Decision.choices, db_index=True)
    reason_code = models.CharField(max_length=64, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    decided_by = models.PositiveBigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    _DECISION_FIELDS = (
        "tenant_id",
        "decision_no",
        "application_case_id",
        "attempt_no",
        "decision",
        "reason_code",
        "reason",
        "decided_by",
    )

    class Meta:
        db_table = "hr13_title_qualification_decision"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "decision_no"),
                name="uq_hr13_qualification_tenant_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr13_qualification_case_attempt",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "application_case_id", "decision"),
                name="idx_hr13_qualification_case",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._DECISION_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._DECISION_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "TITLE_QUALIFICATION_DECISION_IMMUTABLE: review decisions "
                        "must be appended, not edited in place"
                    )
        return super().save(*args, **kwargs)


class TitleMaterialSnapshot(HrTenantScopedModel):
    """Immutable review-time evidence snapshot for one title application.

    ``source_domain``/``source_ref`` point back to the upstream provider fact;
    ``snapshot_json`` and ``content_hash`` preserve exactly what reviewers saw.
    HR13 does not edit the upstream authority record through this model.
    """

    class Status(models.TextChoices):
        ATTACHED = "ATTACHED", "Attached"
        RETURNED = "RETURNED", "Returned for correction"
        ACCEPTED = "ACCEPTED", "Accepted"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    material_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    material_type = models.CharField(max_length=64)
    display_name = models.CharField(max_length=200)
    source_domain = models.CharField(max_length=32, default="SELF")
    source_ref = models.CharField(max_length=128, blank=True, default="")
    source_version = models.CharField(max_length=64, blank=True, default="")
    content_hash = models.CharField(max_length=64)
    snapshot_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ATTACHED, db_index=True
    )
    supersedes_snapshot_id = models.UUIDField(null=True, blank=True)

    _IMMUTABLE_STATUSES = frozenset({Status.ACCEPTED, Status.WITHDRAWN})
    _SNAPSHOT_FIELDS = (
        "tenant_id",
        "material_no",
        "application_case_id",
        "material_type",
        "display_name",
        "source_domain",
        "source_ref",
        "source_version",
        "content_hash",
        "snapshot_json",
        "status",
        "supersedes_snapshot_id",
    )

    class Meta:
        db_table = "hr13_title_material_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "material_no"), name="uq_hr13_material_tenant_no"
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "application_case_id", "status"),
                name="idx_hr13_material_case_status",
            ),
            models.Index(
                fields=("tenant_id", "source_domain", "source_ref"),
                name="idx_hr13_material_source",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._SNAPSHOT_FIELDS
            ).first()
            if persisted and persisted["status"] in self._IMMUTABLE_STATUSES:
                changed = [
                    field
                    for field in self._SNAPSHOT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "TITLE_MATERIAL_SNAPSHOT_IMMUTABLE: accepted/withdrawn review evidence "
                        "must not be edited in place"
                    )
        return super().save(*args, **kwargs)


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
