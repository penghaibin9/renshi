"""HR12 finalized assessment provider for HR09 evidence evaluation."""

from __future__ import annotations

import uuid
from datetime import date

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)
from hr_staff.models import HrStaffMaster

PROVIDER_VERSION = "hr12-final-assessment-v1"


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
        if source_version and source_version != PROVIDER_VERSION:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_VERSION_UNSUPPORTED",
                message=(
                    f"Requested HR12 source version {source_version!r} is not "
                    f"available; current provider is {PROVIDER_VERSION}."
                ),
                provider_version=PROVIDER_VERSION,
            )

        if staff_master_id is None:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
                message="Canonical HR03 StaffMaster is required for HR12 evidence.",
                provider_version=PROVIDER_VERSION,
            )

        staff_exists = HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id=staff_master_id,
            person_id=person_id,
        ).exists()
        if not staff_exists:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
                message="The requested person/staff identity is not valid in this tenant.",
                provider_version=PROVIDER_VERSION,
            )

        case_ids = HrAssessmentCase.objects.filter(
            tenant_id=tenant_id,
            staff_id=staff_master_id,
        ).values_list("id", flat=True)
        results = list(
            HrFinalAssessmentResult.objects.filter(
                tenant_id=tenant_id,
                case_id__in=case_ids,
                status="FINALIZED",
                finalized_at__isnull=False,
                finalized_at__date__lte=as_of,
            ).order_by("finalized_at", "id")
        )

        items = [
            ProviderEvidenceItem(
                source_domain="HR12",
                source_object_type="HrFinalAssessmentResult",
                source_object_id=str(result.id),
                evidence_date=result.finalized_at.date(),
                title="正式考核结果",
                role=result.assessment_type,
                quantitative_value=(
                    float(result.calculated_score)
                    if result.calculated_score is not None
                    else None
                ),
                verification_status=result.status,
                snapshot_json={
                    "assessmentType": result.assessment_type,
                    "gradeCode": result.grade_code,
                    "displayGrade": result.display_grade_snapshot_json,
                    "calculatedScore": str(result.calculated_score)
                    if result.calculated_score is not None
                    else None,
                    "resultVersionNo": result.result_version_no,
                    "contentHash": result.content_hash,
                    "policyVersionId": str(result.policy_version_id)
                    if result.policy_version_id
                    else None,
                    "decisionSessionId": str(result.decision_session_id)
                    if result.decision_session_id
                    else None,
                },
            )
            for result in results
        ]
        source_updated_at = max((result.updated_at for result in results), default=None)
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
