"""Final review-ranking authority for HR14 appointment competitions."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import Max

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentQuotaReservation,
    AppointmentRankingResult,
)


class AppointmentRankingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentRankingOutcome:
    ranking: AppointmentRankingResult
    case: AppointmentApplicationCase
    created: bool


class AppointmentRankingService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentRankingError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _score(value) -> Decimal:
        try:
            score = Decimal(str(value)).quantize(Decimal("0.0001"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_SCORE_INVALID", "total_score must be numeric"
            ) from exc
        if score < 0:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_SCORE_INVALID", "total_score cannot be negative"
            )
        return score

    def _idempotent(
        self,
        *,
        ranking_no: str,
        case_id,
        total_score: Decimal,
        rank_no: int,
        outcome: str,
        score_snapshot: dict,
    ) -> AppointmentRankingOutcome | None:
        existing = AppointmentRankingResult.objects.filter(
            tenant_id=self.tenant_id,
            ranking_no=ranking_no,
        ).first()
        if existing is None:
            return None
        if (
            existing.application_case_id != case_id
            or existing.total_score != total_score
            or existing.rank_no != rank_no
            or existing.outcome != outcome
            or existing.score_snapshot_json != score_snapshot
        ):
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_IDEMPOTENCY_CONFLICT",
                "ranking_no already exists with different content",
            )
        case = AppointmentApplicationCase.objects.filter(
            tenant_id=self.tenant_id, id=case_id
        ).first()
        if case is None:
            raise AppointmentRankingError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        return AppointmentRankingOutcome(existing, case, False)

    def _release_non_selected_quota(self, case: AppointmentApplicationCase) -> None:
        quota = (
            AppointmentQuotaReservation.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, application_case=case)
            .first()
        )
        if quota is None or quota.status == AppointmentQuotaReservation.Status.RELEASED:
            return
        if quota.status == AppointmentQuotaReservation.Status.CONSUMED:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_QUOTA_ALREADY_CONSUMED",
                "a non-selected application cannot already have consumed appointment quota",
            )
        from hr_appointment.services.quota_service import AppointmentQuotaService

        AppointmentQuotaService(
            self.tenant_id, actor_user_id=self.actor_user_id
        ).release(quota.id)

    @transaction.atomic
    def finalize(
        self,
        *,
        case_id,
        ranking_no: str,
        total_score,
        rank_no: int,
        outcome: str,
        score_snapshot: Optional[dict] = None,
    ) -> AppointmentRankingOutcome:
        ranking_no = str(ranking_no or "").strip()
        outcome = str(outcome or "").strip().upper()
        if not ranking_no:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_NO_REQUIRED", "ranking_no is required"
            )
        if outcome not in AppointmentRankingResult.Outcome.values:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_OUTCOME_INVALID", f"unsupported outcome: {outcome}"
            )
        try:
            rank_no = int(rank_no)
        except (TypeError, ValueError) as exc:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RANK_INVALID", "rank_no must be a positive integer"
            ) from exc
        if rank_no <= 0:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RANK_INVALID", "rank_no must be a positive integer"
            )
        score = self._score(total_score)
        score_snapshot = {} if score_snapshot is None else score_snapshot
        if not isinstance(score_snapshot, dict):
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_SNAPSHOT_INVALID", "score_snapshot must be an object"
            )

        replay = self._idempotent(
            ranking_no=ranking_no,
            case_id=case_id,
            total_score=score,
            rank_no=rank_no,
            outcome=outcome,
            score_snapshot=score_snapshot,
        )
        if replay is not None:
            return replay

        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=case_id)
            .first()
        )
        if case is None:
            raise AppointmentRankingError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        if case.status != AppointmentApplicationCase.Status.UNDER_REVIEW:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_INVALID_CASE_STATE",
                f"ranking requires UNDER_REVIEW case, got {case.status}",
            )

        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, batch_no=case.batch_no)
            .first()
        )
        if batch is None:
            raise AppointmentRankingError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        if batch.status not in {
            AppointmentBatch.Status.REVIEWING,
            AppointmentBatch.Status.RANKING,
        }:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_INVALID_BATCH_STATE",
                f"ranking requires REVIEWING/RANKING batch, got {batch.status}",
            )

        last_attempt = (
            AppointmentRankingResult.objects.filter(
                tenant_id=self.tenant_id,
                application_case_id=case.id,
            ).aggregate(max_attempt=Max("attempt_no"))["max_attempt"]
            or 0
        )
        ranking = AppointmentRankingResult.objects.create(
            tenant_id=self.tenant_id,
            ranking_no=ranking_no,
            application_case_id=case.id,
            batch_no=case.batch_no,
            position_instance_id=case.position_instance_id,
            attempt_no=last_attempt + 1,
            total_score=score,
            rank_no=rank_no,
            outcome=outcome,
            score_snapshot_json=score_snapshot,
            finalized_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if outcome == AppointmentRankingResult.Outcome.SELECTED:
            case.status = AppointmentApplicationCase.Status.PROPOSED
        elif outcome == AppointmentRankingResult.Outcome.WAITLIST:
            self._release_non_selected_quota(case)
            case.status = AppointmentApplicationCase.Status.WAITLIST
        else:
            self._release_non_selected_quota(case)
            case.status = AppointmentApplicationCase.Status.NOT_SELECTED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return AppointmentRankingOutcome(ranking, case, True)
