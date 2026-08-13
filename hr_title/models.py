"""HR13 title evaluation authority models."""

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
            ("hr.title.panel", "维护 HR13 专家评议与表决"),
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
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "review_round_id", "status"),
                name="idx_hr13_assignment_round",
            ),
        ]


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
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "person_id", "status"),
                name="idx_hr13_result_tenant_person",
            ),
        ]
