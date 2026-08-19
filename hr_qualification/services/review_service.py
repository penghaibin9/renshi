"""HR09 formal review service with frozen-evidence authority gates."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from hr_qualification.constants import ApplicationStatus, ReviewStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherFormalReview,
    HrDoubleTeacherFormalReviewSection,
)
from hr_qualification.services.evidence_authority_service import (
    EvidenceAuthorityError,
    EvidenceAuthorityService,
)


class ReviewError(Exception):
    def __init__(self, code: str, message: str | None = None):
        if message is None:
            message = code
            code = "REVIEW_ERROR"
        self.code = code
        super().__init__(message)


class FormalReviewService:
    @staticmethod
    def _lock_application(application: HrDoubleTeacherApplication) -> HrDoubleTeacherApplication:
        locked = (
            HrDoubleTeacherApplication.objects.select_for_update()
            .select_related("batch_id__rule_pack_version_id")
            .filter(id=application.id, tenant_id=application.tenant_id)
            .first()
        )
        if locked is None:
            raise ReviewError("APPLICATION_NOT_FOUND", "application not found inside tenant")
        return locked

    @staticmethod
    def _assert_frozen_evidence(application):
        try:
            return EvidenceAuthorityService.require_frozen_application_evidence(
                application,
                for_update=True,
            )
        except EvidenceAuthorityError as exc:
            raise ReviewError(exc.code, str(exc)) from exc

    @staticmethod
    @transaction.atomic
    def start(
        application: HrDoubleTeacherApplication,
        reviewer_id: int | None = None,
    ) -> HrDoubleTeacherFormalReview:
        application = FormalReviewService._lock_application(application)
        existing = (
            HrDoubleTeacherFormalReview.objects.select_for_update()
            .filter(application_id=application)
            .order_by("-created_at", "-id")
            .first()
        )
        if existing is not None and existing.status in {
            ReviewStatus.IN_REVIEW,
            ReviewStatus.COMPLETED,
        }:
            FormalReviewService._assert_frozen_evidence(application)
            return existing

        if application.status != ApplicationStatus.SUBMITTED:
            raise ReviewError(
                "FORMAL_REVIEW_INVALID_APPLICATION_STATE",
                f"formal review requires SUBMITTED, got {application.status}",
            )
        FormalReviewService._assert_frozen_evidence(application)

        review = HrDoubleTeacherFormalReview.objects.create(
            application_id=application,
            reviewer_id=reviewer_id,
            status=ReviewStatus.IN_REVIEW,
            started_at=timezone.now(),
        )
        application.status = ApplicationStatus.FORMAL_REVIEW
        application.version += 1
        application.save(update_fields=["status", "version", "updated_at"])
        return review

    @staticmethod
    def save_section(
        review: HrDoubleTeacherFormalReview,
        section_code: str,
        result: str,
        reviewer_id: int | None = None,
        comment: str = "",
        issue_tags: list | None = None,
        evidence_item_ids: list | None = None,
    ) -> HrDoubleTeacherFormalReviewSection:
        if review.status == ReviewStatus.COMPLETED:
            raise ReviewError(
                "FORMAL_REVIEW_COMPLETED_IMMUTABLE",
                "completed formal review cannot be edited",
            )
        section, _ = HrDoubleTeacherFormalReviewSection.objects.update_or_create(
            formal_review_id=review,
            section_code=section_code,
            defaults={
                "result": result,
                "reviewer_id": reviewer_id,
                "reviewed_at": timezone.now(),
                "comment": comment,
                "issue_tags": issue_tags or [],
                "evidence_item_ids": evidence_item_ids or [],
            },
        )
        return section

    @staticmethod
    @transaction.atomic
    def complete(
        review: HrDoubleTeacherFormalReview,
        overall_result: str,
        conclusion: str = "",
    ) -> HrDoubleTeacherFormalReview:
        review = (
            HrDoubleTeacherFormalReview.objects.select_for_update()
            .select_related("application_id__batch_id__rule_pack_version_id")
            .get(id=review.id)
        )
        application = FormalReviewService._lock_application(review.application_id)
        FormalReviewService._assert_frozen_evidence(application)
        if review.status == ReviewStatus.COMPLETED:
            return review
        if application.status != ApplicationStatus.FORMAL_REVIEW:
            raise ReviewError(
                "FORMAL_REVIEW_INVALID_APPLICATION_STATE",
                f"review completion requires FORMAL_REVIEW, got {application.status}",
            )
        sections = list(review.sections.all())
        if not sections:
            raise ReviewError(
                "FORMAL_REVIEW_SECTION_REQUIRED",
                "At least one review section is required before completing formal review.",
            )
        unreviewed = [section for section in sections if not section.result]
        if unreviewed:
            raise ReviewError(
                "FORMAL_REVIEW_SECTION_INCOMPLETE",
                f"{len(unreviewed)} section(s) have no result.",
            )
        review.overall_result = overall_result
        review.conclusion = conclusion
        review.status = ReviewStatus.COMPLETED
        review.completed_at = timezone.now()
        review.save(
            update_fields=[
                "overall_result",
                "conclusion",
                "status",
                "completed_at",
                "updated_at",
            ]
        )
        return review
