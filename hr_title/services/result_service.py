"""Professional title result authority service.

Formal HR13 title results are append-only facts.  EFFECTIVE/REVISED/REVOKED
rows are never edited in place; revisions and revocations create a successor
row linked by ``supersedes_result_id``.  This preserves the historical chain
needed by HR14/HR15/HR17/HR18 consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_title.models import ProfessionalTitleResult, TitleApplicationCase


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
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _validate_dates(self, payload: TitleResultInput) -> None:
        if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
            raise TitleResultError(
                "TITLE_RESULT_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )

    def _create_fact(
        self,
        *,
        case: TitleApplicationCase,
        payload: TitleResultInput,
        status: str,
        supersedes_result_id=None,
    ) -> ProfessionalTitleResult:
        self._validate_dates(payload)
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

    @transaction.atomic
    def make_effective(
        self,
        *,
        application_case_id,
        payload: TitleResultInput,
    ) -> ProfessionalTitleResult:
        """Create the first formal result from a publicity-complete case."""
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

        # Locking the case serializes first-result creation.  A second caller
        # must not create another root result for the same application.
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

    def _lock_terminal_fact(self, result_id) -> ProfessionalTitleResult:
        result = (
            ProfessionalTitleResult.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise TitleResultError("TITLE_RESULT_NOT_FOUND", "title result not found")

        # A formal fact may have only one direct successor.  This prevents two
        # concurrent revisions from branching the immutable history chain.
        if ProfessionalTitleResult.objects.filter(
            tenant_id=self.tenant_id,
            supersedes_result_id=result.id,
        ).exists():
            raise TitleResultError(
                "TITLE_RESULT_ALREADY_SUPERSEDED",
                "title result already has a successor fact",
            )
        return result

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
        """Append a REVISED successor; never mutate the previous fact."""
        current = self._lock_terminal_fact(result_id)
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
        """Append a REVOKED successor that records when the title ceased."""
        current = self._lock_terminal_fact(result_id)
        if current.status == ProfessionalTitleResult.Status.REVOKED:
            raise TitleResultError("TITLE_RESULT_REVOKED", "result is already revoked")
        if revoked_at < current.effective_from:
            raise TitleResultError(
                "TITLE_RESULT_REVOCATION_DATE_INVALID",
                "revocation cannot predate the superseded result",
            )

        case = self._case_for_result(current)
        payload = TitleResultInput(
            result_no=result_no,
            title_code=current.title_code,
            title_name=current.title_name,
            title_series_code=current.title_series_code,
            title_level_code=current.title_level_code,
            effective_from=revoked_at,
        )
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
