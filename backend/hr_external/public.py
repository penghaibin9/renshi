"""HR08 source-owned external engagement evidence.

Historical eligibility is derived from the engagement's formal lifecycle and
half-open effective interval. DRAFT/pre-activation/error states never become
qualification evidence. Current terminal states can still prove an earlier
active interval when a formal ``end_at`` boundary exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import HrExternalEngagement

PROVIDER_VERSION = "hr08-engagement-evidence-v1"
FORMAL_STATUSES = {
    ExternalEngagementStatus.ACTIVE,
    ExternalEngagementStatus.REVIEW_DUE,
    ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
    ExternalEngagementStatus.EXITING,
    ExternalEngagementStatus.EXPIRED,
    ExternalEngagementStatus.ENDED,
    ExternalEngagementStatus.ARCHIVED,
}
TERMINAL_FORMAL_STATUSES = {
    ExternalEngagementStatus.EXPIRED,
    ExternalEngagementStatus.ENDED,
    ExternalEngagementStatus.ARCHIVED,
}


class ExternalEngagementEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ExternalEngagementEvidenceRow:
    engagement_id: Any
    engagement_no: str
    person_id: Any
    category_code: str
    category_name: str
    start_at: date
    end_at: date | None
    source_status: str
    updated_at: datetime

    def snapshot(self) -> dict:
        return {
            "engagementId": str(self.engagement_id),
            "engagementNo": self.engagement_no,
            "personId": str(self.person_id),
            "categoryCode": self.category_code,
            "categoryName": self.category_name,
            "startAt": self.start_at.isoformat(),
            "endAt": self.end_at.isoformat() if self.end_at else None,
            "effectiveStatus": "ACTIVE",
            "sourceCurrentStatus": self.source_status,
        }


@dataclass(frozen=True)
class ExternalEngagementEvidence:
    rows: tuple[ExternalEngagementEvidenceRow, ...]
    uncertain_engagement_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


def get_formal_engagement_evidence(
    *,
    tenant_id: int,
    person_id,
    as_of: date,
    source_version: str | None = None,
) -> ExternalEngagementEvidence:
    if not tenant_id:
        raise ExternalEngagementEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise ExternalEngagementEvidenceUnavailable(
            "AS_OF_REQUIRED", "as_of must be a date"
        )
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise ExternalEngagementEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR08 source version: {source_version}",
        )

    candidates = list(
        HrExternalEngagement.objects.filter(
            tenant_id=tenant_id,
            person_id_id=person_id,
            start_at__lte=as_of,
            status__in=FORMAL_STATUSES,
        )
        .select_related("category_id")
        .order_by("start_at", "id")
    )

    rows = []
    uncertain = []
    for engagement in candidates:
        if engagement.end_at is not None and engagement.end_at <= as_of:
            continue
        category = engagement.category_id
        if int(category.tenant_id) != int(tenant_id):
            raise ExternalEngagementEvidenceUnavailable(
                "CATEGORY_TENANT_MISMATCH",
                "HR08 engagement references a category from a different tenant",
            )
        if engagement.status in TERMINAL_FORMAL_STATUSES and engagement.end_at is None:
            # A terminal current state without its effective end boundary cannot
            # prove whether a historical as_of was inside the formal engagement.
            uncertain.append(engagement.id)
            continue
        rows.append(
            ExternalEngagementEvidenceRow(
                engagement_id=engagement.id,
                engagement_no=engagement.engagement_no,
                person_id=engagement.person_id_id,
                category_code=category.code,
                category_name=category.name,
                start_at=engagement.start_at,
                end_at=engagement.end_at,
                source_status=engagement.status,
                updated_at=engagement.updated_at,
            )
        )

    return ExternalEngagementEvidence(
        rows=tuple(rows),
        uncertain_engagement_ids=tuple(uncertain),
    )
