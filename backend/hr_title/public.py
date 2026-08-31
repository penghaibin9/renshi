"""Public read contract for formal HR13 professional-title results.

Downstream domains consume this boundary instead of trusting request-provided
title snapshots or reaching into HR13 models with guessed identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from hr_title.models import ProfessionalTitleResult

PROVIDER_VERSION = "hr13-professional-title-v1"


class TitleEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ProfessionalTitleEvidence:
    result_id: UUID
    result_no: str
    person_id: UUID
    application_case_id: UUID
    title_code: str
    title_name: str
    title_series_code: str
    title_level_code: str
    effective_from: date
    effective_to: date | None
    status: str
    supersedes_result_id: UUID | None
    source_version: str = PROVIDER_VERSION

    def snapshot(self) -> dict:
        return {
            "titleResultId": str(self.result_id),
            "resultNo": self.result_no,
            "personId": str(self.person_id),
            "applicationCaseId": str(self.application_case_id),
            "titleCode": self.title_code,
            "titleName": self.title_name,
            "titleSeriesCode": self.title_series_code,
            "titleLevelCode": self.title_level_code,
            "effectiveFrom": self.effective_from.isoformat(),
            "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
            "status": self.status,
        }


def get_effective_title_evidence(
    *,
    tenant_id: int,
    person_id,
    result_id,
    as_of: date,
    source_version: str | None = None,
) -> ProfessionalTitleEvidence:
    """Return one formal HR13 result only if it is authoritative at ``as_of``."""

    if not tenant_id:
        raise TitleEvidenceUnavailable("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
    if not isinstance(as_of, date):
        raise TitleEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version and source_version != PROVIDER_VERSION:
        raise TitleEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR13 source version: {source_version}",
        )

    result = ProfessionalTitleResult.objects.filter(
        tenant_id=tenant_id,
        id=result_id,
        person_id=person_id,
    ).first()
    if result is None:
        raise TitleEvidenceUnavailable(
            "TITLE_RESULT_IDENTITY_MISMATCH",
            "requested HR13 result is outside this tenant/person identity boundary",
        )
    if result.effective_from > as_of or (
        result.effective_to is not None and result.effective_to <= as_of
    ):
        raise TitleEvidenceUnavailable(
            "TITLE_RESULT_NOT_EFFECTIVE_AS_OF",
            "requested HR13 result is not effective at the requested as-of date",
        )
    if result.status == ProfessionalTitleResult.Status.REVOKED:
        raise TitleEvidenceUnavailable(
            "TITLE_RESULT_REVOKED", "revoked HR13 title result is not valid evidence"
        )

    successor = (
        ProfessionalTitleResult.objects.filter(
            tenant_id=tenant_id,
            supersedes_result_id=result.id,
            person_id=person_id,
            effective_from__lte=as_of,
        )
        .order_by("effective_from", "created_at", "id")
        .first()
    )
    if successor is not None:
        if successor.status == ProfessionalTitleResult.Status.REVOKED:
            raise TitleEvidenceUnavailable(
                "TITLE_RESULT_REVOKED_AS_OF",
                "a revocation superseded the requested HR13 result by the as-of date",
            )
        raise TitleEvidenceUnavailable(
            "TITLE_RESULT_SUPERSEDED",
            "a newer formal HR13 result superseded the requested result by the as-of date",
        )

    if result.status not in {
        ProfessionalTitleResult.Status.EFFECTIVE,
        ProfessionalTitleResult.Status.REVISED,
    }:
        raise TitleEvidenceUnavailable(
            "TITLE_RESULT_NOT_FORMAL",
            f"unsupported HR13 title result status: {result.status}",
        )

    return ProfessionalTitleEvidence(
        result_id=result.id,
        result_no=result.result_no,
        person_id=result.person_id,
        application_case_id=result.application_case_id,
        title_code=result.title_code,
        title_name=result.title_name,
        title_series_code=result.title_series_code,
        title_level_code=result.title_level_code,
        effective_from=result.effective_from,
        effective_to=result.effective_to,
        status=result.status,
        supersedes_result_id=result.supersedes_result_id,
    )
