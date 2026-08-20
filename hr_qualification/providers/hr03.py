"""HR03 education/degree/work-history providers for HR09 evidence evaluation.

All business filtering and canonical identity validation live behind the HR03
source-owned public contract. This consumer does not query HR03 tables directly.
"""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

PROVIDER_VERSION = "hr03-background-evidence-v1"


class _Hr03BackgroundProvider(HrEvidenceProvider):
    kinds: frozenset[str]
    source_domain: str

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        from hr_staff.public import (
            BackgroundEvidenceUnavailable,
            get_verified_background_evidence,
        )

        try:
            evidence = get_verified_background_evidence(
                tenant_id=tenant_id,
                person_id=person_id,
                staff_id=staff_master_id,
                as_of=as_of,
                source_version=source_version,
            )
        except BackgroundEvidenceUnavailable as exc:
            return ProviderEvidenceResult.unavailable(
                reason_code=exc.code,
                message=str(exc),
                provider_version=PROVIDER_VERSION,
            )

        rows = [row for row in evidence.rows if row.kind in self.kinds]
        items = [
            ProviderEvidenceItem(
                source_domain=(
                    "HR03_DEGREE" if row.kind == "DEGREE" else self.source_domain
                ),
                source_object_type=row.source_object_type,
                source_object_id=str(row.source_object_id),
                evidence_date=row.evidence_date,
                title=row.title,
                role=row.role,
                quantitative_value=row.quantitative_value,
                verification_status=row.verification_status,
                snapshot_json=dict(row.snapshot),
            )
            for row in rows
        ]
        source_updated_at = max(
            (row.updated_at for row in rows),
            default=None,
        )
        return ProviderEvidenceResult.ok(
            items=items,
            source_updated_at=source_updated_at,
            provider_version=PROVIDER_VERSION,
        )


class Hr03EducationProvider(_Hr03BackgroundProvider):
    provider_key = "HR03_EDUCATION"
    owner_domain = "hr_staff"
    timeout_seconds = 5
    sensitivity = "RESTRICTED_HR"
    kinds = frozenset({"EDUCATION", "DEGREE"})
    source_domain = "HR03_EDUCATION"


class Hr03WorkHistoryProvider(_Hr03BackgroundProvider):
    provider_key = "HR03_WORK_HISTORY"
    owner_domain = "hr_staff"
    timeout_seconds = 5
    sensitivity = "RESTRICTED_HR"
    kinds = frozenset({"WORK"})
    source_domain = "HR03_WORK_HISTORY"
