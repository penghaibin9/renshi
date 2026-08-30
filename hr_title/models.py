"""HR13 title evaluation authority models."""

from __future__ import annotations

import hashlib
import json

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
            ("hr.title.panel", "维护 HR13 专家评议与表决"),
            ("hr.title.panel.correct", "追加更正 HR13 已产生事实的评委分配"),
            ("hr.title.publicity", "维护 HR13 公示与异议复核"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "policy_code", "version_no"),
                name="uq_hr13_policy_tenant_code_ver",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr13_policy_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status"),
                name="idx_hr13_policy_tenant_status",
            ),
        ]


class TitleApplicationCase(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        RETURNED = "RETURNED", "Returned for correction"
        ELIGIBLE = "ELIGIBLE", "Eligibility passed"
        REJECTED = "REJECTED", "Eligibility rejected"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        REVIEW_NOT_PASSED = "REVIEW_NOT_PASSED", "Review not passed"
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
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr13_title_application_case"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "case_no"),
                name="uq_hr13_case_tenant_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr13_case_tenant_person",
            ),
            models.Index(
                fields=("tenant_id", "batch_no", "status"),
                name="idx_hr13_case_tenant_batch",
            ),
        ]


class TitleQualificationDecision(HrTenantScopedModel):
    class Decision(models.TextChoices):
        ELIGIBLE = "ELIGIBLE", "Eligible"
        RETURNED = "RETURNED", "Returned for correction"
        REJECTED = "REJECTED", "Rejected"

    decision_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField()
    attempt_no = models.PositiveIntegerField()
    decision = models.CharField(
        max_length=16,
        choices=Decision.choices,
        db_index=True,
    )
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
        max_length=16,
        choices=Status.choices,
        default=Status.ATTACHED,
        db_index=True,
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
                fields=("tenant_id", "material_no"),
                name="uq_hr13_material_tenant_no",
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


class TitleReviewRound(HrTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PASSED = "PASSED", "Passed"
        NOT_PASSED = "NOT_PASSED", "Not passed"
        CANCELLED = "CANCELLED", "Cancelled"

    round_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField(db_index=True)
    attempt_no = models.PositiveIntegerField()
    required_ballots = models.PositiveIntegerField()
    required_pass_votes = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    opened_by = models.PositiveBigIntegerField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.PositiveBigIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_snapshot_json = models.JSONField(default=dict, blank=True)

    _FROZEN_FIELDS = (
        "tenant_id",
        "round_no",
        "application_case_id",
        "attempt_no",
        "required_ballots",
        "required_pass_votes",
        "opened_by",
    )

    class Meta:
        db_table = "hr13_title_review_round"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "round_no"),
                name="uq_hr13_review_round_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr13_review_case_attempt",
            ),
            models.CheckConstraint(
                condition=Q(required_ballots__gte=1),
                name="ck_hr13_review_ballots_positive",
            ),
            models.CheckConstraint(
                condition=Q(required_pass_votes__gte=1)
                & Q(required_pass_votes__lte=models.F("required_ballots")),
                name="ck_hr13_review_pass_threshold",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "application_case_id", "status"),
                name="idx_hr13_review_case_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FROZEN_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._FROZEN_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "TITLE_REVIEW_ROUND_IMMUTABLE: quorum and review identity are frozen"
                    )
        return super().save(*args, **kwargs)


class TitleReviewAssignmentQuerySet(models.QuerySet):
    """Close ORM bulk paths that can rewrite panel evidence in place."""

    _PROTECTED_FIELDS = frozenset(
        {
            "tenant_id",
            "assignment_no",
            "application_case_id",
            "review_round_id",
            "reviewer_staff_id",
            "reviewer_role",
            "status",
            "conflict_declared",
            "conflict_note",
            "assigned_by",
            "assigned_at",
            "responded_at",
            "supersedes_assignment_id",
            "replacement_reason_code",
            "replacement_reason",
            "replacement_authorized_by",
            "replacement_at",
        }
    )

    def update(self, **kwargs):
        if self._PROTECTED_FIELDS.intersection(kwargs):
            raise ValueError(
                "TITLE_REVIEW_ASSIGNMENT_IMMUTABLE: panel evidence cannot be bulk-updated"
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if objs and self._PROTECTED_FIELDS.intersection(fields):
            raise ValueError(
                "TITLE_REVIEW_ASSIGNMENT_IMMUTABLE: panel evidence cannot be bulk-updated"
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if objs:
            raise ValueError(
                "TITLE_REVIEW_ASSIGNMENT_SERVICE_REQUIRED: use TitlePanelService"
            )
        return []

    def delete(self):
        if self.exists():
            raise ValueError(
                "TITLE_REVIEW_ASSIGNMENT_APPEND_ONLY: panel evidence cannot be deleted"
            )
        return (0, {})


class TitleReviewAssignment(HrTenantScopedModel):
    class Role(models.TextChoices):
        EXPERT = "EXPERT", "Expert"
        COMMITTEE = "COMMITTEE", "Committee member"
        CHAIR = "CHAIR", "Chair"

    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    assignment_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField(db_index=True)
    review_round_id = models.UUIDField(db_index=True)
    reviewer_staff_id = models.UUIDField()
    reviewer_role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.EXPERT,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ASSIGNED,
        db_index=True,
    )
    conflict_declared = models.BooleanField(default=False, db_index=True)
    conflict_note = models.TextField(blank=True, default="")
    assigned_by = models.PositiveBigIntegerField(null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    supersedes_assignment_id = models.UUIDField(null=True, blank=True)
    replacement_reason_code = models.CharField(max_length=64, blank=True, default="")
    replacement_reason = models.TextField(blank=True, default="")
    replacement_authorized_by = models.PositiveBigIntegerField(null=True, blank=True)
    replacement_at = models.DateTimeField(null=True, blank=True)

    objects = TitleReviewAssignmentQuerySet.as_manager()

    _IDENTITY_FIELDS = (
        "tenant_id",
        "assignment_no",
        "application_case_id",
        "review_round_id",
        "reviewer_staff_id",
        "reviewer_role",
        "assigned_by",
        "supersedes_assignment_id",
        "replacement_reason_code",
        "replacement_reason",
        "replacement_authorized_by",
        "replacement_at",
    )
    _RESPONSE_FIELDS = (
        "status",
        "conflict_declared",
        "conflict_note",
        "responded_at",
    )

    class Meta:
        db_table = "hr13_title_review_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "assignment_no"),
                name="uq_hr13_review_assignment_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "review_round_id", "reviewer_staff_id"),
                name="uq_hr13_review_round_reviewer",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "supersedes_assignment_id"),
                name="uq_hr13_assignment_supersedes",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        supersedes_assignment_id__isnull=True,
                        replacement_reason_code="",
                        replacement_reason="",
                        replacement_authorized_by__isnull=True,
                        replacement_at__isnull=True,
                    )
                    | (
                        Q(supersedes_assignment_id__isnull=False)
                        & ~Q(replacement_reason_code="")
                        & ~Q(replacement_reason="")
                        & Q(replacement_authorized_by__isnull=False)
                        & Q(replacement_at__isnull=False)
                    )
                ),
                name="ck_hr13_assignment_lineage",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "review_round_id", "status"),
                name="idx_hr13_assignment_round",
            ),
            models.Index(
                fields=("tenant_id", "application_case_id", "review_round_id"),
                name="idx_hr13_assignment_case",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *(self._IDENTITY_FIELDS + self._RESPONSE_FIELDS)
            ).first()
            if persisted:
                identity_changed = [
                    field
                    for field in self._IDENTITY_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if identity_changed:
                    raise ValueError(
                        "TITLE_REVIEW_ASSIGNMENT_IDENTITY_IMMUTABLE: use append-only replacement"
                    )

                response_changed = [
                    field
                    for field in self._RESPONSE_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                has_fact = bool(persisted["responded_at"]) or TitleReviewBallot.objects.filter(
                    tenant_id=persisted["tenant_id"], assignment_id=self.pk
                ).exists()
                has_successor = type(self)._base_manager.filter(
                    tenant_id=persisted["tenant_id"],
                    supersedes_assignment_id=self.pk,
                ).exists()
                if response_changed and (has_fact or has_successor):
                    raise ValueError(
                        "TITLE_REVIEW_ASSIGNMENT_FACT_IMMUTABLE: response/conflict evidence is frozen"
                    )
                if response_changed:
                    valid_response = (
                        persisted["status"] == self.Status.ASSIGNED
                        and self.status in {self.Status.ACCEPTED, self.Status.DECLINED}
                        and self.responded_at is not None
                        and (
                            not self.conflict_declared
                            or (
                                self.status == self.Status.DECLINED
                                and bool(str(self.conflict_note or "").strip())
                            )
                        )
                    )
                    if not valid_response:
                        raise ValueError(
                            "TITLE_REVIEW_ASSIGNMENT_RESPONSE_INVALID: use respond_assignment"
                        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "TITLE_REVIEW_ASSIGNMENT_APPEND_ONLY: panel evidence cannot be deleted"
        )


class TitleReviewBallot(HrTenantScopedModel):
    class Recommendation(models.TextChoices):
        PASS = "PASS", "Pass"
        FAIL = "FAIL", "Fail"
        ABSTAIN = "ABSTAIN", "Abstain"

    ballot_no = models.CharField(max_length=64)
    review_round_id = models.UUIDField(db_index=True)
    assignment_id = models.UUIDField()
    recommendation = models.CharField(
        max_length=16,
        choices=Recommendation.choices,
        db_index=True,
    )
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    rationale = models.TextField(blank=True, default="")
    submitted_by = models.PositiveBigIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    _FACT_FIELDS = (
        "tenant_id",
        "ballot_no",
        "review_round_id",
        "assignment_id",
        "recommendation",
        "score",
        "rationale",
        "submitted_by",
    )

    class Meta:
        db_table = "hr13_title_review_ballot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "ballot_no"),
                name="uq_hr13_review_ballot_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "review_round_id", "assignment_id"),
                name="uq_hr13_review_round_assignment_ballot",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "review_round_id", "recommendation"),
                name="idx_hr13_ballot_round",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._FACT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "TITLE_REVIEW_BALLOT_IMMUTABLE: submitted ballots must be appended, not edited"
                    )
        return super().save(*args, **kwargs)


class TitlePublicityRecord(HrTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    publicity_no = models.CharField(max_length=64)
    application_case_id = models.UUIDField(db_index=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    content_snapshot_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    opened_by = models.PositiveBigIntegerField(null=True, blank=True)
    closed_by = models.PositiveBigIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr13_title_publicity_record"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "publicity_no"),
                name="uq_hr13_publicity_tenant_no",
            ),
            models.CheckConstraint(
                condition=Q(end_at__gt=models.F("start_at")),
                name="ck_hr13_publicity_time_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "application_case_id", "status"),
                name="idx_hr13_publicity_case",
            ),
        ]


class TitleAppealRecord(HrTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        REJECTED = "REJECTED", "Rejected"
        UPHELD = "UPHELD", "Upheld"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    appeal_no = models.CharField(max_length=64)
    publicity_id = models.UUIDField(db_index=True)
    application_case_id = models.UUIDField(db_index=True)
    appellant_ref = models.CharField(max_length=128, blank=True, default="")
    reason = models.TextField()
    evidence_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    resolution = models.TextField(blank=True, default="")
    resolved_by = models.PositiveBigIntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr13_title_appeal_record"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "appeal_no"),
                name="uq_hr13_appeal_tenant_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "publicity_id", "status"),
                name="idx_hr13_appeal_publicity",
            ),
        ]


class ProfessionalTitleResultQuerySet(models.QuerySet):
    """Block ORM bulk paths that would bypass the fact model's save guard."""

    def update(self, **kwargs):
        if self.exists():
            raise ValueError(
                "TITLE_RESULT_IMMUTABLE: formal title results cannot be updated in place"
            )
        return 0

    def bulk_update(self, objs, fields, batch_size=None):
        if objs:
            raise ValueError(
                "TITLE_RESULT_IMMUTABLE: formal title results cannot be bulk-updated"
            )
        return 0

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if objs:
            raise ValueError(
                "TITLE_RESULT_SEAL_REQUIRED: use ProfessionalTitleResultService to seal facts"
            )
        return []

    def delete(self):
        if self.exists():
            raise ValueError(
                "TITLE_RESULT_IMMUTABLE: formal title results cannot be deleted"
            )
        return (0, {})


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
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.EFFECTIVE,
        db_index=True,
    )
    supersedes_result_id = models.UUIDField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True)

    objects = ProfessionalTitleResultQuerySet.as_manager()

    _FACT_FIELDS = (
        "tenant_id",
        "result_no",
        "person_id",
        "application_case_id",
        "title_code",
        "title_name",
        "title_series_code",
        "title_level_code",
        "effective_from",
        "effective_to",
        "status",
        "supersedes_result_id",
        "content_hash",
        "sealed_at",
        "created_by",
        "updated_by",
    )

    class Meta:
        db_table = "hr13_professional_title_result"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "result_no"),
                name="uq_hr13_result_tenant_no",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr13_result_effective_range",
            ),
            models.CheckConstraint(
                condition=Q(content_hash__regex=r"^[0-9a-f]{64}$"),
                name="ck_hr13_result_hash_format",
            ),
            models.CheckConstraint(
                condition=Q(sealed_at__isnull=False),
                name="ck_hr13_result_sealed_at",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr13_result_tenant_person",
            ),
        ]

    def integrity_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "resultNo": self.result_no,
            "personId": str(self.person_id),
            "applicationCaseId": str(self.application_case_id),
            "titleCode": self.title_code,
            "titleName": self.title_name,
            "titleSeriesCode": self.title_series_code,
            "titleLevelCode": self.title_level_code,
            "effectiveFrom": self.effective_from.isoformat(),
            "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
            "status": self.status,
            "supersedesResultId": (
                str(self.supersedes_result_id) if self.supersedes_result_id else None
            ),
            "sealedAt": self.sealed_at.isoformat() if self.sealed_at else None,
            "createdBy": self.created_by,
            "updatedBy": self.updated_by,
        }

    def calculate_content_hash(self) -> str:
        encoded = json.dumps(
            self.integrity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted:
                changed = [
                    field
                    for field in self._FACT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "TITLE_RESULT_IMMUTABLE: sealed formal title results must be "
                        "superseded, not edited in place; changed="
                        + ",".join(sorted(changed))
                    )
        if self._state.adding:
            if self.sealed_at is None:
                raise ValueError("TITLE_RESULT_SEAL_REQUIRED: sealed_at is required")
            expected_hash = self.calculate_content_hash()
            if self.content_hash != expected_hash:
                raise ValueError(
                    "TITLE_RESULT_HASH_INVALID: content_hash does not match the formal result"
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("TITLE_RESULT_IMMUTABLE: formal title results cannot be deleted")
        return super().delete(*args, **kwargs)
