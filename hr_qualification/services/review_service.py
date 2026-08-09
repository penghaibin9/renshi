"""
hr_qualification/services/review_service.py —— 评审编排服务（总册 §69-82）。

- Formal Review（形式审查）
- Panel 管理 + 冲突检测
- Score Sheet 生命周期（DRAFT→SUBMITTED→LOCKED）
- Vote
- Panel Decision + School Final Decision
"""

from __future__ import annotations

import datetime as _dt
import uuid
from datetime import datetime, timezone

from django.db import transaction

from hr_qualification.constants import (
    ApplicationStatus,
    ConflictStatus,
    FinalDecisionType,
    PanelDecisionType,
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


class ReviewError(Exception):
    pass


class ReviewService:
    """评审编排服务。"""

    # ---- 形式审查 ----

    @staticmethod
    def formal_review(
        application: HrDoubleTeacherApplication,
        decision: str,
        remarks: str = "",
    ) -> HrDoubleTeacherApplication:
        allowed = {ApplicationStatus.FORMAL_REVIEW, ApplicationStatus.SUBMITTED}
        if application.status not in allowed:
            raise ReviewError(f"Application not in reviewable status: {application.status}")

        # 形式审查结论映射到合法 ApplicationStatus
        valid_decisions = {
            "RETURNED": ApplicationStatus.RETURNED,
            "ELIGIBLE": ApplicationStatus.ELIGIBLE,
            "INELIGIBLE": ApplicationStatus.NOT_RECOGNIZED,
            "NEEDS_ESCALATION": ApplicationStatus.PANEL_REVIEW,
        }
        target_status = valid_decisions.get(decision)
        if target_status is None:
            raise ReviewError(f"Invalid formal review decision: {decision}")

        application.status = target_status
        application.version += 1
        application.save()
        return application

    # ---- Score Sheet ----

    @staticmethod
    def create_score_sheet(
        application_id: uuid.UUID,
        panel_member_id: int,
        rubric_version_id: str = "",
    ) -> HrDoubleTeacherScoreSheet:
        return HrDoubleTeacherScoreSheet.objects.create(
            application_id_id=application_id,
            panel_member_id_id=panel_member_id,
            rubric_version_id=rubric_version_id,
            status=ScoreSheetStatus.DRAFT,
        )

    @staticmethod
    def submit_score(sheet_id: uuid.UUID, scores_json: dict) -> HrDoubleTeacherScoreSheet:
        sheet = HrDoubleTeacherScoreSheet.objects.select_for_update().get(id=sheet_id)
        if sheet.status != ScoreSheetStatus.DRAFT:
            raise ReviewError(f"Score sheet is {sheet.status}, cannot submit.")

        sheet.scores_json = scores_json
        sheet.status = ScoreSheetStatus.SUBMITTED
        sheet.submitted_at = datetime.now(timezone.utc)
        sheet.version += 1
        sheet.save()
        return sheet

    @staticmethod
    def lock_score(sheet_id: uuid.UUID) -> HrDoubleTeacherScoreSheet:
        sheet = HrDoubleTeacherScoreSheet.objects.select_for_update().get(id=sheet_id)
        if sheet.status != ScoreSheetStatus.SUBMITTED:
            raise ReviewError(f"Score sheet is {sheet.status}, cannot lock.")

        sheet.status = ScoreSheetStatus.LOCKED
        sheet.version += 1
        sheet.save()
        return sheet

    # ---- Vote ----

    @staticmethod
    def cast_vote(
        application_id: uuid.UUID,
        panel_id: uuid.UUID,
        panel_member_id: int,
        choice: str,
    ) -> HrDoubleTeacherVote:
        return HrDoubleTeacherVote.objects.create(
            application_id_id=application_id,
            panel_id_id=panel_id,
            panel_member_id_id=panel_member_id,
            choice=choice,
        )

    # ---- Panel Decision ----

    @staticmethod
    def create_panel_decision(
        application_id: uuid.UUID,
        panel_id: uuid.UUID,
        decision: str,
        recommended_level: str = "",
        reason_summary: str = "",
    ) -> HrDoubleTeacherPanelDecision:
        return HrDoubleTeacherPanelDecision.objects.create(
            application_id_id=application_id,
            panel_id_id=panel_id,
            decision=decision,
            recommended_level=recommended_level,
            reason_summary=reason_summary,
            finalized_at=datetime.now(timezone.utc),
        )

    # ---- Final Decision ----

    @staticmethod
    def finalize(
        application: HrDoubleTeacherApplication,
        decision: str,
        recognized_level: str | None = None,
        effective_from: str | None = None,
        decision_authority: str = "",
        meeting_ref: str = "",
    ) -> tuple[HrDoubleTeacherFinalDecision, HrDoubleTeacherRecognition | None]:
        """学校最终认定（创建 FinalDecision + Recognition）。"""
        with transaction.atomic():
            application = HrDoubleTeacherApplication.objects.select_for_update().get(
                id=application.id
            )

            # 防重复
            if HrDoubleTeacherFinalDecision.objects.filter(application_id=application).exists():
                raise ReviewError("FINAL_DECISION_ALREADY_EXISTS")

            fd = HrDoubleTeacherFinalDecision.objects.create(
                application_id=application,
                decision=decision,
                recognized_level=recognized_level,
                effective_from=_dt.date.fromisoformat(effective_from) if effective_from else None,
                decision_authority=decision_authority,
                meeting_ref=meeting_ref,
                published_at=datetime.now(timezone.utc),
            )

            recognition = None
            if decision == FinalDecisionType.RECOGNIZE and recognized_level:
                # 若已有旧认定 → SUPERSEDED
                old_recognitions = HrDoubleTeacherRecognition.objects.filter(
                    tenant_id=application.tenant_id,
                    person_id=application.person_id,
                    status=RecognitionStatus.ACTIVE,
                )
                for old in old_recognitions:
                    old.status = RecognitionStatus.SUPERSEDED
                    old.version += 1
                    old.save()

                recognition = HrDoubleTeacherRecognition.objects.create(
                    tenant_id=application.tenant_id,
                    person_id=application.person_id,
                    staff_master_id=application.staff_master_id,
                    recognition_no=f"DT-{application.tenant_id}-{uuid.uuid4().hex[:8].upper()}",
                    level=recognized_level,
                    rule_pack_version_id=application.batch_id.rule_pack_version_id,
                    batch_id=application.batch_id,
                    application_id=application,
                    effective_from=fd.effective_from or _dt.date.today(),
                    status=RecognitionStatus.PENDING_EFFECTIVE,
                    recognition_authority=decision_authority,
                )

                # Backfill EvidenceUsage with recognition_id
                HrEvidenceUsage.objects.filter(
                    application_id=application,
                ).update(recognition_id=recognition)

            application.status = (
                ApplicationStatus.RECOGNIZED
                if decision == FinalDecisionType.RECOGNIZE
                else ApplicationStatus.NOT_RECOGNIZED
            )
            application.version += 1
            application.save()

        return fd, recognition

    # ---- 冲突检测 ----

    @staticmethod
    def detect_conflict(
        panel_member: HrDoubleTeacherPanelMember,
        applicant_person_id: uuid.UUID,
    ) -> str:
        """简单冲突检测（占位；实际应接入 HR03 关系图谱）。"""
        return ConflictStatus.CLEAR

    @staticmethod
    def mark_recused(
        panel_member_id: int,
        reason: str = "",
    ) -> HrDoubleTeacherPanelMember:
        member = HrDoubleTeacherPanelMember.objects.get(id=panel_member_id)
        member.conflict_status = ConflictStatus.RECUSED
        member.save()
        return member
