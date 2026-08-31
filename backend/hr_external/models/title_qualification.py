"""HR08 title appointments, qualification reviews and performance reviews.

These models intentionally keep honorary titles separate from active external
engagements. Qualification review consumes verified HR09 facts when available;
performance review feeds renewal decisions without mutating finalized facts.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ExternalTitleAppointmentType,
    PerformanceResult,
    QualificationReviewStatus,
)


class HrExternalTitleAppointment(models.Model):
    """Title appointment fact; an honorary title never grants employment access."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_title_appointments",
    )
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="title_appointments",
    )
    title_type = models.CharField(
        max_length=32,
        choices=ExternalTitleAppointmentType.choices,
        default=ExternalTitleAppointmentType.OTHER,
    )
    title_name = models.CharField(max_length=200)
    conferring_authority = models.CharField(max_length=200, blank=True, default="")
    conferred_at = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_honorary_only = models.BooleanField(
        default=False,
        help_text=(
            "Honorary-only title. It does not by itself grant teaching, payroll, "
            "door-access, office-system, or academic-system permissions."
        ),
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Title Appointment")
        verbose_name_plural = _("HR External Title Appointments")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "person_id", "title_type", "valid_from"],
                name="uniq_hr_external_title_appt",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_title_appt_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id", "title_type"],
                name="hex_title_appt_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "is_honorary_only"],
                name="hex_title_appt_honorary_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.title_type} {self.title_name}"


class HrExternalQualificationReview(models.Model):
    """Pre-engagement qualification review referencing verified HR09 evidence."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_qualification_reviews",
    )
    case_id = models.ForeignKey(
        "hr_external.HrExternalHiringCase",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="qualification_reviews",
    )
    status = models.CharField(
        max_length=24,
        choices=QualificationReviewStatus.choices,
        default=QualificationReviewStatus.PENDING,
    )
    # Provider reference to an HR09 verified qualification fact.
    hr09_credential_ref = models.CharField(max_length=64, blank=True, default="")
    # Evidence can be staged until HR09 verification is available.
    staging_evidence = models.JSONField(default=list, blank=True)
    reviewer = models.BigIntegerField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Qualification Review")
        verbose_name_plural = _("HR External Qualification Reviews")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_qual_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id", "status"],
                name="hex_qual_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "case_id", "status"],
                name="hex_qual_case_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] qual review {self.status}"


class HrExternalPerformanceReview(models.Model):
    """External-engagement performance review used by renewal decisions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="performance_reviews",
    )
    period = models.CharField(max_length=64)
    task_completion = models.TextField(blank=True, default="")
    teaching_quality_ref = models.CharField(max_length=64, blank=True, default="")
    host_org_rating = models.CharField(max_length=16, blank=True, default="")
    compliance_result = models.CharField(max_length=32, blank=True, default="")
    contribution_summary = models.TextField(blank=True, default="")
    result = models.CharField(
        max_length=24,
        choices=PerformanceResult.choices,
        blank=True,
        default="",
    )
    reviewer = models.BigIntegerField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Performance Review")
        verbose_name_plural = _("HR External Performance Reviews")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_id", "period"],
                name="uniq_hr_external_perf_period",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_perf_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "result"],
                name="hex_perf_eng_result_idx",
            ),
            models.Index(
                fields=["tenant_id", "result"],
                name="hex_perf_result_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] perf {self.period} {self.result}"
