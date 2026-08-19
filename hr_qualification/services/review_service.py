"""HR09 review orchestration with frozen-evidence authority gates."""

from __future__ import annotations

import datetime as _dt
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from hr_qualification.constants import (
    ApplicationStatus,
    ConflictStatus,
    FinalDecisionType,
    RecognitionStatus,
    ScoreSheetStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherPanelDecision,
    HrDoubleTeacherPanelMember,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherReviewPanel,
    HrDoubleTeacherScoreSheet,
    HrDoubleTeacherVote,
    HrEvidenceUsage,
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


class ReviewService:
    """Review orchestration backed by the real HR09 review models."""

    @staticmethod
    def _lock_application(
        application: HrDoubleTeacherApplication,
    ) -> HrDoubleTeacherApplication:
        locked = (
            HrDoubleTeacherApplication.objects.select_for_update()
            .select_related("batch_id__rule_pack_version_id")
            .filter(id=application.id, tenant_id=application.tenant_id)
            .first()
        )
        if locked is None:
            raise ReviewError(
                "APPLICATION_NOT_FOUND",
                "application not found inside tenant",
            )
        return locked

    @staticmethod
    def _assert_frozen_evidence(application, *, for_update: bool = False):
        try:
            return EvidenceAuthorityService.require_frozen_application_evidence(
                application,
                for_update=for_update,
            )
        except EvidenceAuthorityError as exc:
            raise ReviewError(exc.code, str(exc)) from exc

    @staticmethod
    @transaction.atomic
    def formal_review(
        application: HrDoubleTeacherApplication,
        decision: str,
        remarks: str = "",
    ) -> HrDoubleTeacherApplication:
        """Complete the formal-review decision against the frozen submission."""
        application = ReviewService._lock_application(application)
        if application.status not in {
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.FORMAL_REVIEW,
        }:
            raise ReviewError(
                "FORMAL_REVIEW_INVALID_APPLICATION_STATE",
                f"application is {application.status}, not reviewable",
            )
        ReviewService._assert_frozen_evidence(application, for_update=True)

        valid_decisions = {
            "RETURNED": ApplicationStatus.RETURNED,
            ApplicationStatus.RETURNED: ApplicationStatus.RETURNED,
            "ELIGIBLE": ApplicationStatus.ELIGIBLE,
            ApplicationStatus.ELIGIBLE: ApplicationStatus.ELIGIBLE,
            "INELIGIBLE": ApplicationStatus.NOT_RECOGNIZED,
            ApplicationStatus.NOT_RECOGNIZED: ApplicationStatus.NOT_RECOGNIZED,
            "NEEDS_ESCALATION": ApplicationStatus.PANEL_REVIEW,
            ApplicationStatus.PANEL_REVIEW: ApplicationStatus.PANEL_REVIEW,
        }
        target_status = valid_decisions.get(decision)
        if target_status is None:
            raise ReviewError(
                "FORMAL_REVIEW_INVALID_DECISION",
                f"invalid formal review decision: {decision}",
            )

        application.status = target_status
        application.version += 1
        application.save(update_fields=["status", "version", "updated_at"])
        return application

    @staticmethod
    def create_score_sheet(
        application_id: uuid.UUID,
        panel_member_id: uuid.UUID,
        rubric_version_id: str = "",
    ) -> HrDoubleTeacherScoreSheet:
        return HrDoubleTeacherScoreSheet.objects.create(
            application_id_id=application_id,
            panel_member_id_id=panel_member_id,
            rubric_version_id=rubric_version_id,
            status=ScoreSheetStatus.DRAFT,
        )

    @staticmethod
    @transaction.atomic
    def submit_score(
        sheet_id: uuid.UUID,
        scores_json: dict,
    ) -> HrDoubleTeacherScoreSheet:
        sheet = (
            HrDoubleTeacherScoreSheet.objects.select_for_update()
            .select_related("application_id__batch_id__rule_pack_version_id")
            .get(id=sheet_id)
        )
        ReviewService._assert_frozen_evidence(
            sheet.application_id,
            for_update=True,
        )
        if sheet.status != ScoreSheetStatus.DRAFT:
            raise ReviewError(
                "SCORE_SHEET_INVALID_STATE",
                f"score sheet is {sheet.status}, cannot submit",
            )

        sheet.scores_json = scores_json
        sheet.status = ScoreSheetStatus.SUBMITTED
        sheet.submitted_at = timezone.now()
        sheet.version += 1
        sheet.save(
            update_fields=[
                "scores_json",
                "status",
                "submitted_at",
                "version",
                "updated_at",
            ]
        )
        return sheet

    @staticmethod
    @transaction.atomic
    def lock_score(sheet_id: uuid.UUID) -> HrDoubleTeacherScoreSheet:
        sheet = (
            HrDoubleTeacherScoreSheet.objects.select_for_update()
            .select_related("application_id__batch_id__rule_pack_version_id")
            .get(id=sheet_id)
        )
        ReviewService._assert_frozen_evidence(
            sheet.application_id,
            for_update=True,
        )
        if sheet.status == ScoreSheetStatus.LOCKED:
            return sheet
        if sheet.status != ScoreSheetStatus.SUBMITTED:
            raise ReviewError(
                "SCORE_SHEET_INVALID_STATE",
                f"score sheet is {sheet.status}, cannot lock",
            )

        sheet.status = ScoreSheetStatus.LOCKED
        sheet.version += 1
        sheet.save(update_fields=["status", "version", "updated_at"])
        return sheet

    @staticmethod
    @transaction.atomic
    def cast_vote(
        application_id: uuid.UUID,
        panel_id: uuid.UUID,
        panel_member_id: uuid.UUID,
        choice: str,
    ) -> HrDoubleTeacherVote:
        application = (
            HrDoubleTeacherApplication.objects.select_for_update()
            .select_related("batch_id__rule_pack_version_id")
            .get(id=application_id)
        )
        panel = HrDoubleTeacherReviewPanel.objects.filter(id=panel_id).first()
        member = HrDoubleTeacherPanelMember.objects.filter(
            id=panel_member_id,
            panel_id_id=panel_id,
        ).first()
        if panel is None or member is None:
            raise ReviewError(
                "PANEL_MEMBER_NOT_FOUND",
                "panel/member relationship is invalid",
            )
        if str(panel.batch_id_id) != str(application.batch_id_id):
            raise ReviewError(
                "PANEL_SCOPE_MISMATCH",
                "panel does not belong to the application batch",
            )
        ReviewService._assert_frozen_evidence(application, for_update=True)
        try:
            return HrDoubleTeacherVote.objects.create(
                application_id=application,
                panel_id=panel,
                panel_member_id=member,
                choice=choice,
            )
        except IntegrityError as exc:
            raise ReviewError(
                "VOTE_ALREADY_EXISTS",
                "panel member already voted for this application",
            ) from exc

    @staticmethod
    @transaction.atomic
    def create_panel_decision(
        application_id: uuid.UUID,
        panel_id: uuid.UUID,
        decision: str,
        recommended_level: str = "",
        reason_summary: str = "",
    ) -> HrDoubleTeacherPanelDecision:
        application = (
            HrDoubleTeacherApplication.objects.select_for_update()
            .select_related("batch_id__rule_pack_version_id")
            .get(id=application_id)
        )
        panel = HrDoubleTeacherReviewPanel.objects.filter(id=panel_id).first()
        if panel is None or str(panel.batch_id_id) != str(application.batch_id_id):
            raise ReviewError(
                "PANEL_SCOPE_MISMATCH",
                "panel does not belong to the application batch",
            )
        ReviewService._assert_frozen_evidence(application, for_update=True)
        try:
            return HrDoubleTeacherPanelDecision.objects.create(
                application_id=application,
                panel_id=panel,
                decision=decision,
                recommended_level=recommended_level,
                reason_summary=reason_summary,
                finalized_at=timezone.now(),
            )
        except IntegrityError as exc:
            raise ReviewError(
                "PANEL_DECISION_ALREADY_EXISTS",
                "application already has a panel decision",
            ) from exc

    @staticmethod
    @transaction.atomic
    def finalize(
        application: HrDoubleTeacherApplication,
        decision: str,
        recognized_level: str | None = None,
        effective_from: str | None = None,
        decision_authority: str = "",
        meeting_ref: str = "",
    ) -> tuple[HrDoubleTeacherFinalDecision, HrDoubleTeacherRecognition | None]:
        """Create the immutable school decision from the exact frozen evidence."""
        application = ReviewService._lock_application(application)
        ReviewService._assert_frozen_evidence(application, for_update=True)

        if HrDoubleTeacherFinalDecision.objects.select_for_update().filter(
            application_id=application
        ).exists():
            raise ReviewError(
                "FINAL_DECISION_ALREADY_EXISTS",
                "application already has a final decision",
            )

        try:
            effective_date = (
                _dt.date.fromisoformat(effective_from)
                if effective_from
                else timezone.localdate()
            )
        except (TypeError, ValueError) as exc:
            raise ReviewError(
                "FINAL_DECISION_INVALID_EFFECTIVE_DATE",
                f"invalid effective_from: {effective_from}",
            ) from exc

        try:
            final_decision = HrDoubleTeacherFinalDecision.objects.create(
                application_id=application,
                decision=decision,
                recognized_level=recognized_level,
                effective_from=effective_date if decision == FinalDecisionType.RECOGNIZE else None,
                decision_authority=decision_authority,
                meeting_ref=meeting_ref,
                published_at=timezone.now(),
            )
        except IntegrityError as exc:
            raise ReviewError(
                "FINAL_DECISION_ALREADY_EXISTS",
                "application already has a final decision",
            ) from exc

        recognition = None
        if decision == FinalDecisionType.RECOGNIZE:
            if not recognized_level:
                raise ReviewError(
                    "RECOGNIZED_LEVEL_REQUIRED",
                    "recognized_level is required for a recognition decision",
                )
            old_recognitions = list(
                HrDoubleTeacherRecognition.objects.select_for_update().filter(
                    tenant_id=application.tenant_id,
                    person_id=application.person_id,
                    status=RecognitionStatus.ACTIVE,
                )
            )
            for old in old_recognitions:
                old.status = RecognitionStatus.SUPERSEDED
                old.effective_to = effective_date
                old.version += 1
                old.save(
                    update_fields=[
                        "status",
                        "effective_to",
                        "version",
                        "updated_at",
                    ]
                )

            recognition = HrDoubleTeacherRecognition.objects.create(
                tenant_id=application.tenant_id,
                person_id=application.person_id,
                staff_master_id=application.staff_master_id,
                recognition_no=(
                    f"DT-{application.tenant_id}-{uuid.uuid4().hex[:8].upper()}"
                ),
                level=recognized_level,
                rule_pack_version_id=application.batch_id.rule_pack_version_id,
                batch_id=application.batch_id,
                application_id=application,
                effective_from=effective_date,
                status=RecognitionStatus.PENDING_EFFECTIVE,
                recognition_authority=decision_authority,
            )
            HrEvidenceUsage.objects.filter(application_id=application).update(
                recognition_id=recognition
            )

        application.status = (
            ApplicationStatus.RECOGNIZED
            if decision == FinalDecisionType.RECOGNIZE
            else ApplicationStatus.NOT_RECOGNIZED
        )
        application.version += 1
        application.save(update_fields=["status", "version", "updated_at"])
        return final_decision, recognition

    @staticmethod
    def detect_conflict(
        panel_member: HrDoubleTeacherPanelMember,
        applicant_person_id: uuid.UUID,
    ) -> str:
        """Fail neutral until HR03 relationship-graph conflict data is available."""
        return ConflictStatus.CLEAR

    @staticmethod
    def mark_recused(
        panel_member_id: uuid.UUID,
        reason: str = "",
    ) -> HrDoubleTeacherPanelMember:
        member = HrDoubleTeacherPanelMember.objects.get(id=panel_member_id)
        member.conflict_status = ConflictStatus.RECUSED
        member.save(update_fields=["conflict_status"])
        return member
