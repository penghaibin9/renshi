"""HR12 finalized assessment provider for HR09 evidence evaluation.

HR09 consumes only the HR12 source-owned public contract; it does not query HR12
models directly or infer canonical identity from foreign tables.
"""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

PROVIDER_VERSION = "hr12-final-assessment-v2"


class Hr12AssessmentProvider(HrEvidenceProvider):
    provider_key = "HR12_ASSESSMENT"
    owner_domain = "hr_assessment"
    timeout_seconds = 10
    sensitivity = "RESTRICTED_HR"

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        if staff_master_id is None:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
                message="Canonical HR03 StaffMaster is required for HR12 evidence.",
                provider_version=PROVIDER_VERSION,
            )

        from hr_assessment.public import (
            AssessmentEvidenceUnavailable,
            list_finalized_assessment_evidence,
        )

        try:
            evidence_rows = list_finalized_assessment_evidence(
                tenant_id=tenant_id,
                person_id=person_id,
                staff_id=staff_master_id,
                as_of=as_of,
                source_version=source_version,
            )
        except AssessmentEvidenceUnavailable as exc:
            return ProviderEvidenceResult.unavailable(
                reason_code=exc.code,
                message=str(exc),
                provider_version=PROVIDER_VERSION,
            )

        items = [
            ProviderEvidenceItem(
                source_domain="HR12",
                source_object_type="HrFinalAssessmentResult",
                source_object_id=str(evidence.result_id),
                evidence_date=evidence.finalized_at.date(),
                title="正式考核结果",
                role=evidence.assessment_type,
                quantitative_value=(
                    float(evidence.calculated_score)
                    if evidence.calculated_score is not None
                    else None
                ),
                verification_status="FINALIZED",
                snapshot_json=evidence.snapshot(),
            )
            for evidence in evidence_rows
        ]
        source_updated_at = max(
            (evidence.finalized_at for evidence in evidence_rows),
            default=None,
        )
        return ProviderEvidenceResult.ok(
            items,
            source_updated_at=source_updated_at,
            provider_version=PROVIDER_VERSION,
        )


class ResearchProjectProvider(HrEvidenceProvider):
    provider_key = "RESEARCH_PROJECT"
    owner_domain = "external"
    timeout_seconds = 10
    sensitivity = "RESTRICTED_HR"

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        return ProviderEvidenceResult.unavailable(
            reason_code="INTEGRATION_NOT_CONFIGURED",
            message="科研系统对接尚未配置。科研项目/成果转化事实将在对接完成后提供。",
        )
