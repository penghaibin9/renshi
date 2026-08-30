"""Professional title result authority service.

Formal HR13 title results are append-only facts. EFFECTIVE/REVISED/REVOKED
rows are never edited in place. A PUBLICITY case is only eligible for its first
formal result after the latest real publicity record is CLOSED and all appeals
are non-blocking.

HTTP/network retries are exact-idempotent by ``result_no``. A replay with the
same frozen payload returns the existing fact; the same number with different
content fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_title.authority_registry import (
    EVENT_RESULT_PUBLISHED,
    EVENT_RESULT_REVISED,
    EVENT_RESULT_REVOKED,
)

from hr_title.models import (
    ProfessionalTitleResult,
    TitleAppealRecord,
    TitleApplicationCase,
    TitlePolicyVersion,
    TitlePublicityRecord,
    TitleReviewAssignment,
    TitleReviewBallot,
    TitleReviewRound,
)


class TitleResultError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TitleResultInput:
    result_no: str
    title_code: str
    title_name: str
    effective_from: date
    title_series_code: str = ""
    title_level_code: str = ""
    effective_to: Optional[date] = None


@dataclass(frozen=True)
class TitleResultPublicationInput:
    """Non-authoritative request data accepted for the first publication."""

    result_no: str
    effective_from: date
    effective_to: Optional[date] = None


class ProfessionalTitleResultService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise TitleResultError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = str(correlation_id or "")

    @staticmethod
    def _normalize_payload(payload: TitleResultInput) -> TitleResultInput:
        if not isinstance(payload, TitleResultInput):
            raise TitleResultError(
                "TITLE_RESULT_PAYLOAD_INVALID", "result payload must be TitleResultInput"
            )
        if not isinstance(payload.effective_from, date):
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_DATE_INVALID", "effective_from is required"
            )
        if payload.effective_to is not None and not isinstance(payload.effective_to, date):
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_DATE_INVALID", "effective_to must be a date"
            )

        normalized = TitleResultInput(
            result_no=str(payload.result_no or "").strip(),
            title_code=str(payload.title_code or "").strip(),
            title_name=str(payload.title_name or "").strip(),
            title_series_code=str(payload.title_series_code or "").strip(),
            title_level_code=str(payload.title_level_code or "").strip(),
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
        )
        required = {
            "result_no": normalized.result_no,
            "title_code": normalized.title_code,
            "title_name": normalized.title_name,
        }
        for field, value in required.items():
            if not value:
                raise TitleResultError(
                    f"TITLE_RESULT_{field.upper()}_REQUIRED",
                    f"{field} is required",
                )
        limits = {
            "result_no": 64,
            "title_code": 64,
            "title_name": 200,
            "title_series_code": 64,
            "title_level_code": 64,
        }
        for field, limit in limits.items():
            if len(getattr(normalized, field)) > limit:
                raise TitleResultError(
                    "TITLE_RESULT_FIELD_TOO_LONG",
                    f"{field} exceeds {limit} characters",
                )
        if (
            normalized.effective_to is not None
            and normalized.effective_to <= normalized.effective_from
        ):
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )
        return normalized

    def _find_by_result_no(self, result_no: str) -> Optional[ProfessionalTitleResult]:
        return (
            ProfessionalTitleResult.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, result_no=result_no)
            .first()
        )

    @staticmethod
    def _payload_matches(result: ProfessionalTitleResult, payload: TitleResultInput) -> bool:
        return (
            result.result_no == payload.result_no
            and result.title_code == payload.title_code
            and result.title_name == payload.title_name
            and result.title_series_code == payload.title_series_code
            and result.title_level_code == payload.title_level_code
            and result.effective_from == payload.effective_from
            and result.effective_to == payload.effective_to
        )

    def _exact_replay(
        self,
        *,
        existing: ProfessionalTitleResult,
        payload: TitleResultInput,
        status: str,
        supersedes_result_id=None,
        application_case_id=None,
    ) -> ProfessionalTitleResult:
        expected_supersedes = str(supersedes_result_id) if supersedes_result_id else None
        observed_supersedes = (
            str(existing.supersedes_result_id) if existing.supersedes_result_id else None
        )
        if (
            existing.status != status
            or observed_supersedes != expected_supersedes
            or not self._payload_matches(existing, payload)
            or (
                application_case_id is not None
                and str(existing.application_case_id) != str(application_case_id)
            )
        ):
            raise TitleResultError(
                "TITLE_RESULT_IDEMPOTENCY_CONFLICT",
                "result_no already belongs to a different formal title payload",
            )
        return existing

    def _create_fact(
        self,
        *,
        case: TitleApplicationCase,
        payload: TitleResultInput,
        status: str,
        supersedes_result_id=None,
        authority_snapshot=None,
    ) -> ProfessionalTitleResult:
        result = ProfessionalTitleResult(
            tenant_id=self.tenant_id,
            result_no=payload.result_no,
            person_id=case.person_id,
            application_case_id=case.id,
            title_code=payload.title_code,
            title_name=payload.title_name,
            title_series_code=payload.title_series_code,
            title_level_code=payload.title_level_code,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            status=status,
            supersedes_result_id=supersedes_result_id,
            authority_snapshot_json=authority_snapshot or {},
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            sealed_at=timezone.now(),
        )
        result.content_hash = result.calculate_content_hash()
        result.save(force_insert=True)
        return result

    def _emit_result_event(self, event_name: str, result: ProfessionalTitleResult) -> None:
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            payload={
                "resultId": str(result.id),
                "resultNo": result.result_no,
                "personId": str(result.person_id),
                "applicationCaseId": str(result.application_case_id),
                "titleCode": result.title_code,
                "status": result.status,
                "supersedesResultId": (
                    str(result.supersedes_result_id)
                    if result.supersedes_result_id
                    else None
                ),
                "contentHash": result.content_hash,
                "sealedAt": result.sealed_at.isoformat(),
                "authoritySnapshot": result.authority_snapshot_json,
            },
            correlation_id=self.correlation_id,
        )

    def _require_closed_publicity(self, case: TitleApplicationCase) -> TitlePublicityRecord:
        publicity = (
            TitlePublicityRecord.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                application_case_id=case.id,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if publicity is None:
            raise TitleResultError(
                "TITLE_PUBLICITY_REQUIRED",
                "a real publicity record is required before a formal title result",
            )
        if publicity.status != TitlePublicityRecord.Status.CLOSED or publicity.closed_at is None:
            raise TitleResultError(
                "TITLE_PUBLICITY_NOT_CLOSED",
                "the latest publicity record must be closed before a formal title result",
            )
        appeals = TitleAppealRecord.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            publicity_id=publicity.id,
            application_case_id=case.id,
        )
        if appeals.filter(status=TitleAppealRecord.Status.OPEN).exists():
            raise TitleResultError(
                "TITLE_APPEALS_PENDING",
                "open appeals block the formal title result",
            )
        if appeals.filter(status=TitleAppealRecord.Status.UPHELD).exists():
            raise TitleResultError(
                "TITLE_APPEAL_UPHELD",
                "an upheld appeal blocks the formal title result",
            )
        return publicity

    @staticmethod
    def _normalize_publication_input(
        payload: TitleResultPublicationInput,
    ) -> TitleResultPublicationInput:
        if not isinstance(payload, TitleResultPublicationInput):
            raise TitleResultError(
                "TITLE_RESULT_PUBLICATION_PAYLOAD_INVALID",
                "initial publication accepts only operational publication input",
            )
        result_no = str(payload.result_no or "").strip()
        if not result_no:
            raise TitleResultError("TITLE_RESULT_RESULT_NO_REQUIRED", "result_no is required")
        if len(result_no) > 64:
            raise TitleResultError(
                "TITLE_RESULT_FIELD_TOO_LONG", "result_no exceeds 64 characters"
            )
        if not isinstance(payload.effective_from, date):
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_DATE_INVALID", "effective_from is required"
            )
        if payload.effective_to is not None and not isinstance(payload.effective_to, date):
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_DATE_INVALID", "effective_to must be a date"
            )
        if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )
        return TitleResultPublicationInput(
            result_no=result_no,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
        )

    def _published_policy(
        self, case: TitleApplicationCase, effective_from: date
    ) -> TitlePolicyVersion:
        policy = (
            TitlePolicyVersion.objects.select_for_update()
            .filter(id=case.policy_version_id, tenant_id=self.tenant_id)
            .first()
        )
        if policy is None:
            raise TitleResultError(
                "TITLE_RESULT_POLICY_NOT_FOUND",
                "the application does not reference a policy in the same tenant",
            )
        if policy.status != "PUBLISHED" or policy.published_at is None:
            raise TitleResultError(
                "TITLE_RESULT_POLICY_NOT_PUBLISHED",
                "the referenced title policy must be published",
            )
        if policy.content_hash != policy.calculate_content_hash():
            raise TitleResultError(
                "TITLE_RESULT_POLICY_HASH_INVALID",
                "the published title policy hash is missing or invalid",
            )
        if effective_from < policy.effective_from or (
            policy.effective_to is not None and effective_from >= policy.effective_to
        ):
            raise TitleResultError(
                "TITLE_RESULT_POLICY_NOT_EFFECTIVE",
                "effective_from is outside the published policy validity window",
            )
        if not case.requested_title_code.strip() or not case.requested_title_name.strip():
            raise TitleResultError(
                "TITLE_RESULT_TITLE_IDENTITY_MISSING",
                "the frozen application title code and name are required",
            )
        if not policy.title_series_code.strip() or not policy.title_level_code.strip():
            raise TitleResultError(
                "TITLE_RESULT_POLICY_TITLE_IDENTITY_MISSING",
                "the published policy must define title series and level",
            )
        return policy

    def _passed_review_evidence(
        self, case: TitleApplicationCase, policy: TitlePolicyVersion
    ) -> tuple[TitleReviewRound, dict, list[dict]]:
        review_round = (
            TitleReviewRound.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, application_case_id=case.id)
            .order_by("-attempt_no", "-created_at", "-id")
            .first()
        )
        if (
            review_round is None
            or review_round.status != TitleReviewRound.Status.PASSED
            or review_round.closed_at is None
        ):
            raise TitleResultError(
                "TITLE_RESULT_PASSED_REVIEW_REQUIRED",
                "the latest frozen review round must be closed and passed",
            )
        if (
            review_round.required_ballots != policy.required_ballots
            or review_round.required_pass_votes != policy.required_pass_votes
        ):
            raise TitleResultError(
                "TITLE_RESULT_REVIEW_RULE_MISMATCH",
                "the frozen review thresholds do not match the published policy",
            )

        assignments = TitleReviewAssignment.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            review_round_id=review_round.id,
        )
        if assignments.exclude(application_case_id=case.id).exists():
            raise TitleResultError(
                "TITLE_RESULT_REVIEW_EVIDENCE_INCONSISTENT",
                "review assignments cross the application boundary",
            )
        assignment_ids = set(assignments.values_list("id", flat=True))
        all_ballots = TitleReviewBallot.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            review_round_id=review_round.id,
        )
        if all_ballots.exclude(assignment_id__in=assignment_ids).exists():
            raise TitleResultError(
                "TITLE_RESULT_REVIEW_EVIDENCE_INCONSISTENT",
                "a frozen ballot has no assignment in the same review round",
            )
        superseded_ids = set(
            assignments.exclude(supersedes_assignment_id__isnull=True).values_list(
                "supersedes_assignment_id", flat=True
            )
        )
        active_ids = assignment_ids - superseded_ids
        ballots = all_ballots.filter(assignment_id__in=active_ids)
        ballot_count = ballots.count()
        pass_votes = ballots.filter(
            recommendation=TitleReviewBallot.Recommendation.PASS
        ).count()
        fail_votes = ballots.filter(
            recommendation=TitleReviewBallot.Recommendation.FAIL
        ).count()
        abstentions = ballots.filter(
            recommendation=TitleReviewBallot.Recommendation.ABSTAIN
        ).count()
        if ballot_count < policy.required_ballots or pass_votes < policy.required_pass_votes:
            raise TitleResultError(
                "TITLE_RESULT_REVIEW_DECISION_INVALID",
                "frozen ballots do not satisfy the published passing rule",
            )
        closure = {
            "ballots": ballot_count,
            "passVotes": pass_votes,
            "failVotes": fail_votes,
            "abstentions": abstentions,
            "requiredBallots": review_round.required_ballots,
            "requiredPassVotes": review_round.required_pass_votes,
            "supersededBallotsExcluded": all_ballots.exclude(
                assignment_id__in=active_ids
            ).count(),
            "assignmentLineage": [
                {
                    "assignmentId": str(row.id),
                    "supersedesAssignmentId": (
                        str(row.supersedes_assignment_id)
                        if row.supersedes_assignment_id
                        else None
                    ),
                }
                for row in assignments.order_by("assigned_at", "id")
            ],
        }
        if review_round.closure_snapshot_json != closure:
            raise TitleResultError(
                "TITLE_RESULT_REVIEW_SNAPSHOT_INVALID",
                "the closed review snapshot does not match frozen ballots",
            )
        ballot_facts = [
            {
                "ballotId": str(row.id),
                "ballotNo": row.ballot_no,
                "assignmentId": str(row.assignment_id),
                "recommendation": row.recommendation,
                "score": str(row.score) if row.score is not None else None,
                "submittedAt": row.submitted_at.isoformat(),
            }
            for row in ballots.order_by("submitted_at", "id")
        ]
        return review_round, closure, ballot_facts

    @transaction.atomic
    def make_effective(
        self,
        *,
        application_case_id,
        payload: TitleResultPublicationInput,
    ) -> ProfessionalTitleResult:
        """Create the first formal result only after publicity/appeal closure."""
        publication = self._normalize_publication_input(payload)

        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(id=application_case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TitleResultError("TITLE_CASE_NOT_FOUND", "application case not found")
        if case.status not in {
            TitleApplicationCase.Status.PUBLICITY,
            TitleApplicationCase.Status.EFFECTIVE,
        }:
            raise TitleResultError(
                "TITLE_CASE_INVALID_STATE",
                "only a PUBLICITY case can become effective",
            )

        publicity = self._require_closed_publicity(case)
        policy = self._published_policy(case, publication.effective_from)
        review_round, closure, ballot_facts = self._passed_review_evidence(case, policy)
        derived = self._normalize_payload(
            TitleResultInput(
                result_no=publication.result_no,
                title_code=case.requested_title_code,
                title_name=case.requested_title_name,
                title_series_code=policy.title_series_code,
                title_level_code=policy.title_level_code,
                effective_from=publication.effective_from,
                effective_to=publication.effective_to,
            )
        )
        authority_snapshot = {
            "decision": "PASSED",
            "policyVersionId": str(policy.id),
            "policyCode": policy.policy_code,
            "policyVersionNo": policy.version_no,
            "policyContentHash": policy.content_hash,
            "reviewRoundId": str(review_round.id),
            "reviewRoundNo": review_round.round_no,
            "reviewClosure": closure,
            "reviewBallots": ballot_facts,
            "publicityId": str(publicity.id),
            "publicityNo": publicity.publicity_no,
        }

        existing = self._find_by_result_no(derived.result_no)
        if existing is not None:
            replay = self._exact_replay(
                existing=existing,
                payload=derived,
                status=ProfessionalTitleResult.Status.EFFECTIVE,
                application_case_id=application_case_id,
            )
            if replay.authority_snapshot_json != authority_snapshot:
                raise TitleResultError(
                    "TITLE_RESULT_IDEMPOTENCY_CONFLICT",
                    "result_no authority evidence differs from the sealed fact",
                )
            return replay

        if case.status != TitleApplicationCase.Status.PUBLICITY:
            raise TitleResultError(
                "TITLE_CASE_INVALID_STATE",
                "only a PUBLICITY case can become effective",
            )

        if ProfessionalTitleResult.objects.filter(
            tenant_id=self.tenant_id,
            application_case_id=case.id,
        ).exists():
            raise TitleResultError(
                "TITLE_RESULT_ALREADY_EXISTS",
                "formal result already exists for this application",
            )

        result = self._create_fact(
            case=case,
            payload=derived,
            status=ProfessionalTitleResult.Status.EFFECTIVE,
            authority_snapshot=authority_snapshot,
        )
        case.status = TitleApplicationCase.Status.EFFECTIVE
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        self._emit_result_event(EVENT_RESULT_PUBLISHED, result)
        return result

    def _lock_result(self, result_id) -> ProfessionalTitleResult:
        result = (
            ProfessionalTitleResult.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise TitleResultError("TITLE_RESULT_NOT_FOUND", "title result not found")
        return result

    def _require_terminal_fact(self, result: ProfessionalTitleResult) -> None:
        if ProfessionalTitleResult.objects.filter(
            tenant_id=self.tenant_id,
            supersedes_result_id=result.id,
        ).exists():
            raise TitleResultError(
                "TITLE_RESULT_ALREADY_SUPERSEDED",
                "title result already has a successor fact",
            )

    def _case_for_result(self, result: ProfessionalTitleResult) -> TitleApplicationCase:
        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(
                id=result.application_case_id,
                tenant_id=self.tenant_id,
                person_id=result.person_id,
            )
            .first()
        )
        if case is None:
            raise TitleResultError(
                "TITLE_RESULT_CASE_MISMATCH",
                "result application case is missing or outside tenant/person scope",
            )
        return case

    @transaction.atomic
    def revise(
        self,
        *,
        result_id,
        payload: TitleResultInput,
    ) -> ProfessionalTitleResult:
        payload = self._normalize_payload(payload)
        existing = self._find_by_result_no(payload.result_no)
        if existing is not None:
            return self._exact_replay(
                existing=existing,
                payload=payload,
                status=ProfessionalTitleResult.Status.REVISED,
                supersedes_result_id=result_id,
            )

        current = self._lock_result(result_id)
        self._require_terminal_fact(current)
        if current.status == ProfessionalTitleResult.Status.REVOKED:
            raise TitleResultError(
                "TITLE_RESULT_REVOKED",
                "a revoked result cannot be revised",
            )
        case = self._case_for_result(current)
        if payload.effective_from < current.effective_from:
            raise TitleResultError(
                "TITLE_RESULT_REVISION_DATE_INVALID",
                "revision cannot start before the superseded result",
            )
        result = self._create_fact(
            case=case,
            payload=payload,
            status=ProfessionalTitleResult.Status.REVISED,
            supersedes_result_id=current.id,
            authority_snapshot={
                **current.authority_snapshot_json,
                "correction": {
                    "type": "REVISED",
                    "supersedesResultId": str(current.id),
                },
            },
        )
        self._emit_result_event(EVENT_RESULT_REVISED, result)
        return result

    @transaction.atomic
    def revoke(
        self,
        *,
        result_id,
        result_no: str,
        revoked_at: date,
    ) -> ProfessionalTitleResult:
        current = self._lock_result(result_id)
        payload = self._normalize_payload(
            TitleResultInput(
                result_no=result_no,
                title_code=current.title_code,
                title_name=current.title_name,
                title_series_code=current.title_series_code,
                title_level_code=current.title_level_code,
                effective_from=revoked_at,
            )
        )
        existing = self._find_by_result_no(payload.result_no)
        if existing is not None:
            return self._exact_replay(
                existing=existing,
                payload=payload,
                status=ProfessionalTitleResult.Status.REVOKED,
                supersedes_result_id=current.id,
            )

        self._require_terminal_fact(current)
        if current.status == ProfessionalTitleResult.Status.REVOKED:
            raise TitleResultError("TITLE_RESULT_REVOKED", "result is already revoked")
        if revoked_at < current.effective_from:
            raise TitleResultError(
                "TITLE_RESULT_REVOCATION_DATE_INVALID",
                "revocation cannot predate the superseded result",
            )

        case = self._case_for_result(current)
        revoked = self._create_fact(
            case=case,
            payload=payload,
            status=ProfessionalTitleResult.Status.REVOKED,
            supersedes_result_id=current.id,
            authority_snapshot={
                **current.authority_snapshot_json,
                "correction": {
                    "type": "REVOKED",
                    "supersedesResultId": str(current.id),
                },
            },
        )
        case.status = TitleApplicationCase.Status.REVOKED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        self._emit_result_event(EVENT_RESULT_REVOKED, revoked)
        return revoked
