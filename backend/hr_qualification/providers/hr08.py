"""HR08 external-engagement eligibility provider for HR09."""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderError,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

PROVIDER_VERSION = "hr08-engagement-evidence-v1"


class Hr08EngagementProvider(HrEvidenceProvider):
    provider_key = "HR08_ENGAGEMENT"
    owner_domain = "hr_external"
    timeout_seconds = 5
    sensitivity = "RESTRICTED_HR"

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        from hr_external.public import (
            ExternalEngagementEvidenceUnavailable,
            get_formal_engagement_evidence,
        )

        try:
            evidence = get_formal_engagement_evidence(
                tenant_id=tenant_id,
                person_id=person_id,
                as_of=as_of,
                source_version=source_version,
            )
        except ExternalEngagementEvidenceUnavailable as exc:
            return ProviderEvidenceResult.unavailable(
                reason_code=exc.code,
                message=str(exc),
                provider_version=PROVIDER_VERSION,
            )

        items = []
        for engagement in evidence.rows:
            duration_days = max(0, (as_of - engagement.start_at).days)
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR08_ENGAGEMENT",
                    source_object_type="HrExternalEngagement",
                    source_object_id=str(engagement.engagement_id),
                    evidence_date=engagement.start_at,
                    title=f"External Engagement #{engagement.engagement_no}",
                    role=engagement.category_name or engagement.category_code,
                    quantitative_value=float(duration_days),
                    verification_status="VERIFIED",
                    snapshot_json=engagement.snapshot(),
                )
            )

        source_updated_at = max(
            (engagement.updated_at for engagement in evidence.rows),
            default=None,
        )
        if evidence.uncertain_engagement_ids:
            return ProviderEvidenceResult(
                status=ProviderStatus.PARTIAL,
                items=items,
                errors=[
                    ProviderError(
                        code="HR08_ENGAGEMENT_HISTORY_UNAVAILABLE",
                        message=(
                            "historical HR08 engagement values cannot be proven for: "
                            + ",".join(
                                str(value)
                                for value in evidence.uncertain_engagement_ids
                            )
                        ),
                    )
                ],
                source_updated_at=source_updated_at,
                provider_version=PROVIDER_VERSION,
            )
        if not items:
            return ProviderEvidenceResult.not_applicable(
                provider_version=PROVIDER_VERSION
            )
        return ProviderEvidenceResult.ok(
            items=items,
            source_updated_at=source_updated_at,
            provider_version=PROVIDER_VERSION,
        )
