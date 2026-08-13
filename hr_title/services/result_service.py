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

from hr_title.models import (
    ProfessionalTitleResult,
    TitleAppealRecord,
    TitleApplicationCase,
    TitlePublicityRecord,
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


class ProfessionalTitleResultService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitleResultError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

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
    ) -> ProfessionalTitleResult:
        return ProfessionalTitleResult.objects.create(
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
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
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

    @transaction.atomic
    def make_effective(
        self,
        *,
        application_case_id,
        payload: TitleResultInput,
    ) -> ProfessionalTitleResult:
        """Create the first formal result only after publicity/appeal closure."""
        payload = self._normalize_payload(payload)
        existing = self._find_by_result_no(payload.result_no)
        if existing is not None:
            return self._exact_replay(
                existing=existing,
                payload=payload,
                status=ProfessionalTitleResult.Status.EFFECTIVE,
                application_case_id=application_case_id,
            )

        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(id=application_case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TitleResultError("TITLE_CASE_NOT_FOUND", "application case not found")
        if case.status != TitleApplicationCase.Status.PUBLICITY:
            raise TitleResultError(
                "TITLE_CASE_INVALID_STATE",
                "only a PUBLICITY case can become effective",
            )

        self._require_closed_publicity(case)

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
            payload=payload,
            status=ProfessionalTitleResult.Status.EFFECTIVE,
        )
        case.status = TitleApplicationCase.Status.EFFECTIVE
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
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
        return self._create_fact(
            case=case,
            payload=payload,
            status=ProfessionalTitleResult.Status.REVISED,
            supersedes_result_id=current.id,
        )

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
        )
        case.status = TitleApplicationCase.Status.REVOKED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return revoked
