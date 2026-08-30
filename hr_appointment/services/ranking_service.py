"""Server-authoritative review ranking for HR14 appointment competitions.

The request supplies only an idempotency identity. Scores, ordering, outcomes
and the evidence snapshot are derived from sealed HR12 assessment results and
the frozen assessment-cycle ranking rule.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import Max

from horilla.hr_event_service import emit_registered_event
from hr_appointment.authority_registry import EVENT_RANKING_PUBLISHED
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


@dataclass(frozen=True)
class _RankingAuthority:
    total_score: Decimal
    rank_no: int
    outcome: str
    score_snapshot: dict


class AppointmentRankingService:
    GROUP_STATES = {
        AppointmentApplicationCase.Status.UNDER_REVIEW,
        AppointmentApplicationCase.Status.PROPOSED,
        AppointmentApplicationCase.Status.WAITLIST,
        AppointmentApplicationCase.Status.NOT_SELECTED,
    }

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
                "APPOINTMENT_ASSESSMENT_SCORE_INVALID",
                "sealed assessment calculatedScore must be numeric",
            ) from exc
        if not score.is_finite() or score < 0:
            raise AppointmentRankingError(
                "APPOINTMENT_ASSESSMENT_SCORE_INVALID",
                "sealed assessment calculatedScore must be finite and non-negative",
            )
        return score

    @staticmethod
    def _snapshot_hash(value: dict) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _idempotent(self, *, ranking_no: str, case_id) -> AppointmentRankingOutcome | None:
        existing = AppointmentRankingResult.objects.filter(
            tenant_id=self.tenant_id,
            ranking_no=ranking_no,
        ).first()
        if existing is None:
            return None
        if existing.application_case_id != case_id:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_IDEMPOTENCY_CONFLICT",
                "ranking_no already belongs to another application case",
            )
        case = AppointmentApplicationCase.objects.filter(
            tenant_id=self.tenant_id,
            id=case_id,
        ).first()
        if case is None:
            raise AppointmentRankingError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        return AppointmentRankingOutcome(existing, case, False)

    @staticmethod
    def _count(value, *, field: str, allow_zero: bool) -> int:
        if isinstance(value, bool):
            value = None
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RULE_INVALID", f"{field} must be an integer"
            ) from exc
        minimum = 0 if allow_zero else 1
        if result < minimum:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RULE_INVALID",
                f"{field} must be at least {minimum}",
            )
        return result

    def _assessment_authorities(self, *, batch, target):
        from hr_assessment.models import (
            HrAssessmentCase,
            HrAssessmentCycle,
            HrCycleSnapshot,
            HrFinalAssessmentResult,
        )
        from hr_assessment.services.result_correction_service import canonical_result_snapshot
        from hr_appointment.population_models import AppointmentPopulationMemberSnapshot

        unresolved_participants = AppointmentApplicationCase.objects.filter(
            tenant_id=self.tenant_id,
            batch_no=batch.batch_no,
            position_instance_id=target.position_instance_id,
            status=AppointmentApplicationCase.Status.ELIGIBLE,
        )
        if unresolved_participants.exists():
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_PARTICIPANT_SCOPE_INCOMPLETE",
                "all eligible applications for the position must enter review before ranking",
            )
        group = list(
            AppointmentApplicationCase.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                batch_no=batch.batch_no,
                position_instance_id=target.position_instance_id,
                status__in=self.GROUP_STATES,
            )
            .order_by("id")
        )
        if not group or all(item.id != target.id for item in group):
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_PARTICIPANT_SCOPE_INVALID",
                "target application is not in the frozen ranking participant group",
            )
        members = {
            member.person_id: member
            for member in AppointmentPopulationMemberSnapshot.objects.filter(
                tenant_id=self.tenant_id,
                snapshot__tenant_id=self.tenant_id,
                snapshot__batch_id=batch.id,
                person_id__in=[item.person_id for item in group],
            )
        }
        if len(members) != len({item.person_id for item in group}):
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_POPULATION_BOUNDARY_MISSING",
                "every ranking participant must belong to the frozen tenant batch population",
            )

        cycles = list(
            HrAssessmentCycle.objects.filter(
                tenant_id=self.tenant_id,
                cycle_no=batch.batch_no,
                assessment_type=batch.business_type,
            )[:2]
        )
        if len(cycles) != 1:
            raise AppointmentRankingError(
                "APPOINTMENT_ASSESSMENT_CYCLE_REQUIRED",
                "exactly one tenant assessment cycle must match batch_no and business_type",
            )
        cycle = cycles[0]
        cycle_snapshot = HrCycleSnapshot.objects.filter(
            tenant_id=self.tenant_id, cycle_id=cycle.id
        ).first()
        if cycle_snapshot is None:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RULE_REQUIRED",
                "the matching assessment cycle has no frozen rule snapshot",
            )
        ranking_rule = (cycle_snapshot.frozen_reviewer_rules_json or {}).get("ranking")
        if not isinstance(ranking_rule, dict):
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_RULE_REQUIRED",
                "frozen reviewer rules must contain a ranking object",
            )
        selected_count = self._count(
            ranking_rule.get("selectedCount"), field="selectedCount", allow_zero=False
        )
        waitlist_count = self._count(
            ranking_rule.get("waitlistCount", 0), field="waitlistCount", allow_zero=True
        )
        normalized_rule = {
            "selectedCount": selected_count,
            "waitlistCount": waitlist_count,
            "ordering": "TOTAL_SCORE_DESC_PERSON_ID_ASC_CASE_ID_ASC",
        }

        ranked = []
        for application in group:
            member = members[application.person_id]
            assessment_cases = list(
                HrAssessmentCase.objects.filter(
                    tenant_id=self.tenant_id,
                    cycle_id=cycle.id,
                    staff_id=member.staff_id,
                    assessment_type=batch.business_type,
                )[:2]
            )
            if len(assessment_cases) != 1:
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_CASE_REQUIRED",
                    "every participant must have exactly one assessment case in the cycle",
                )
            assessment_case = assessment_cases[0]
            result = HrFinalAssessmentResult.objects.filter(
                tenant_id=self.tenant_id,
                case_id=assessment_case.id,
                cycle_id=cycle.id,
                assessment_type=batch.business_type,
            ).first()
            if result is None or not result.sealed_at:
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_RESULT_REQUIRED",
                    "every participant must have a sealed formal assessment result",
                )
            if result.content_hash != result.calculate_content_hash():
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_RESULT_HASH_INVALID",
                    "sealed assessment result content hash verification failed",
                )
            latest_revision = result.revisions.order_by("-new_version", "-created_at").first()
            if (
                latest_revision is not None
                and latest_revision.content_hash != latest_revision.calculate_content_hash()
            ):
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_RESULT_HASH_INVALID",
                    "sealed assessment correction content hash verification failed",
                )
            effective = canonical_result_snapshot(result)
            if effective.get("status") == "REVOKED":
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_RESULT_REVOKED",
                    "a revoked assessment result cannot participate in ranking",
                )
            if effective.get("status") not in {"FINALIZED", "CORRECTED"}:
                raise AppointmentRankingError(
                    "APPOINTMENT_ASSESSMENT_RESULT_INVALID_STATE",
                    "only a finalized or corrected assessment result can be ranked",
                )
            score = self._score(effective.get("calculatedScore"))
            source = {
                "appointmentCaseId": str(application.id),
                "personId": str(application.person_id),
                "staffId": str(member.staff_id),
                "assessmentCaseId": str(assessment_case.id),
                "assessmentResultId": str(result.id),
                "assessmentResultVersion": int(effective.get("version") or 1),
                "assessmentResultContentHash": result.content_hash,
                "effectiveResultContentHash": (
                    latest_revision.content_hash if latest_revision else result.content_hash
                ),
                "calculatedScore": str(score),
            }
            ranked.append((application, score, source))

        ranked.sort(key=lambda item: (-item[1], str(item[0].person_id), str(item[0].id)))
        authority = {
            "cycleId": str(cycle.id),
            "cycleSnapshotId": str(cycle_snapshot.id),
            "rankingRule": normalized_rule,
            "rankingRuleHash": self._snapshot_hash(normalized_rule),
        }
        return authority, ranked

    def _derive_authority(self, *, batch, target) -> _RankingAuthority:
        authority, ranked = self._assessment_authorities(batch=batch, target=target)
        selected_count = authority["rankingRule"]["selectedCount"]
        waitlist_count = authority["rankingRule"]["waitlistCount"]
        for ordinal, (application, score, source) in enumerate(ranked, start=1):
            if application.id != target.id:
                continue
            if ordinal <= selected_count:
                outcome = AppointmentRankingResult.Outcome.SELECTED
            elif ordinal <= selected_count + waitlist_count:
                outcome = AppointmentRankingResult.Outcome.WAITLIST
            else:
                outcome = AppointmentRankingResult.Outcome.NOT_SELECTED
            snapshot = {
                "authority": authority,
                "participantCount": len(ranked),
                "tieBreak": {
                    "score": str(score),
                    "personId": str(application.person_id),
                    "caseId": str(application.id),
                },
                "sourceAssessment": source,
            }
            snapshot["contentHash"] = self._snapshot_hash(snapshot)
            return _RankingAuthority(score, ordinal, outcome, snapshot)
        raise AppointmentRankingError(
            "APPOINTMENT_RANKING_PARTICIPANT_SCOPE_INVALID",
            "target application disappeared from the ranking participant group",
        )

    def _release_non_selected_quota(self, case):
        quota = AppointmentQuotaReservation.objects.select_for_update().filter(
            tenant_id=self.tenant_id, application_case=case
        ).first()
        if quota is None or quota.status == AppointmentQuotaReservation.Status.RELEASED:
            return
        if quota.status == AppointmentQuotaReservation.Status.CONSUMED:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_QUOTA_ALREADY_CONSUMED",
                "a non-selected application cannot already have consumed appointment quota",
            )
        from hr_appointment.services.quota_service import AppointmentQuotaService

        AppointmentQuotaService(self.tenant_id, actor_user_id=self.actor_user_id).release(
            quota.id
        )

    def _emit_event(self, ranking):
        from hr_staff.models import HrOutboxEvent

        correlation_id = f"hr14-ranking:{ranking.id}"
        payload = {
            "rankingResultId": str(ranking.id),
            "applicationCaseId": str(ranking.application_case_id),
            "batchNo": ranking.batch_no,
            "positionInstanceId": ranking.position_instance_id,
            "totalScore": str(ranking.total_score),
            "rankNo": ranking.rank_no,
            "outcome": ranking.outcome,
            "scoreSnapshotHash": ranking.score_snapshot_json.get("contentHash"),
        }
        existing = HrOutboxEvent.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            event_type=EVENT_RANKING_PUBLISHED,
            correlation_id=correlation_id,
        ).first()
        if existing is not None:
            if existing.payload_json != {**payload, "eventVersion": 1}:
                raise AppointmentRankingError(
                    "APPOINTMENT_RANKING_OUTBOX_CONFLICT",
                    "ranking event already exists with different content",
                )
            return
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_RANKING_PUBLISHED,
            payload=payload,
            correlation_id=correlation_id,
        )

    @transaction.atomic
    def finalize(self, *, case_id, ranking_no: str, **client_authority_fields):
        forbidden = {
            key
            for key, value in client_authority_fields.items()
            if value is not None
            and key in {"total_score", "rank_no", "outcome", "score_snapshot"}
        }
        if forbidden:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_CLIENT_AUTHORITY_FORBIDDEN",
                "total score, rank, outcome and authority snapshot are server-derived",
            )
        ranking_no = str(ranking_no or "").strip()
        if not ranking_no:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_NO_REQUIRED", "ranking_no is required"
            )
        replay = self._idempotent(ranking_no=ranking_no, case_id=case_id)
        if replay is not None:
            return replay

        case = AppointmentApplicationCase.objects.select_for_update().filter(
            tenant_id=self.tenant_id, id=case_id
        ).first()
        if case is None:
            raise AppointmentRankingError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        batch = AppointmentBatch.objects.select_for_update().filter(
            tenant_id=self.tenant_id, batch_no=case.batch_no
        ).first()
        if batch is None:
            raise AppointmentRankingError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        replay = self._idempotent(ranking_no=ranking_no, case_id=case_id)
        if replay is not None:
            return replay
        if batch.status not in {
            AppointmentBatch.Status.REVIEWING,
            AppointmentBatch.Status.RANKING,
        }:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_INVALID_BATCH_STATE",
                f"ranking requires REVIEWING/RANKING batch, got {batch.status}",
            )
        if case.status != AppointmentApplicationCase.Status.UNDER_REVIEW:
            raise AppointmentRankingError(
                "APPOINTMENT_RANKING_INVALID_CASE_STATE",
                f"ranking requires UNDER_REVIEW case, got {case.status}",
            )

        authority = self._derive_authority(batch=batch, target=case)
        last_attempt = (
            AppointmentRankingResult.objects.filter(
                tenant_id=self.tenant_id, application_case_id=case.id
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
            total_score=authority.total_score,
            rank_no=authority.rank_no,
            outcome=authority.outcome,
            score_snapshot_json=authority.score_snapshot,
            finalized_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if authority.outcome == AppointmentRankingResult.Outcome.SELECTED:
            case.status = AppointmentApplicationCase.Status.PROPOSED
        elif authority.outcome == AppointmentRankingResult.Outcome.WAITLIST:
            self._release_non_selected_quota(case)
            case.status = AppointmentApplicationCase.Status.WAITLIST
        else:
            self._release_non_selected_quota(case)
            case.status = AppointmentApplicationCase.Status.NOT_SELECTED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        if batch.status == AppointmentBatch.Status.REVIEWING:
            batch.status = AppointmentBatch.Status.RANKING
            batch.updated_by = self.actor_user_id
            batch.save(update_fields=["status", "updated_by", "updated_at"])
        self._emit_event(ranking)
        return AppointmentRankingOutcome(ranking, case, True)
