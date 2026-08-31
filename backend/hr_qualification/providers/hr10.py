"""HR10 verified development-fact providers for HR09 evidence evaluation.

HR09 consumes HR10 through its source-owned public contract. Fact filtering,
legacy identity mapping and supersede semantics live in HR10, not duplicated in
this consumer.
"""

from __future__ import annotations

import uuid
from datetime import date

from hr10_development.constants import FactType
from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

PROVIDER_VERSION = "hr10-development-fact-v1"


class _Hr10DevelopmentFactProvider(HrEvidenceProvider):
    fact_type: str
    title: str
    quantitative_field: str

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        from hr10_development.public import (
            DevelopmentEvidenceUnavailable,
            get_verified_development_facts_for_person,
        )

        try:
            evidence = get_verified_development_facts_for_person(
                tenant_id=tenant_id,
                person_id=person_id,
                staff_id=staff_master_id,
                as_of=as_of,
                source_version=source_version,
            )
        except DevelopmentEvidenceUnavailable as exc:
            return ProviderEvidenceResult.unavailable(
                reason_code=exc.code,
                message=str(exc),
                provider_version=PROVIDER_VERSION,
            )

        facts = [fact for fact in evidence.facts if fact.fact_type == self.fact_type]
        items = []
        for fact in facts:
            quantitative = getattr(fact, self.quantitative_field, None)
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR10",
                    source_object_type="HrDevelopmentFact",
                    source_object_id=str(fact.fact_id),
                    evidence_date=fact.end_date or fact.valid_from or fact.start_date,
                    title=self.title,
                    role=fact.activity_type or "",
                    quantitative_value=(
                        float(quantitative) if quantitative is not None else None
                    ),
                    verification_status=fact.verification_status,
                    snapshot_json=fact.snapshot(),
                )
            )

        source_updated_at = max(
            (fact.updated_at for fact in facts if fact.updated_at is not None),
            default=None,
        )
        return ProviderEvidenceResult.ok(
            items,
            source_updated_at=source_updated_at,
            provider_version=PROVIDER_VERSION,
        )


class Hr10EnterprisePracticeProvider(_Hr10DevelopmentFactProvider):
    provider_key = "HR10_ENTERPRISE_PRACTICE"
    owner_domain = "hr_development"
    timeout_seconds = 10
    sensitivity = "RESTRICTED_HR"
    fact_type = FactType.ENTERPRISE_PRACTICE
    title = "企业实践（HR10 已核验事实）"
    quantitative_field = "verified_days"


class Hr10TrainingProvider(_Hr10DevelopmentFactProvider):
    provider_key = "HR10_TRAINING"
    owner_domain = "hr_development"
    timeout_seconds = 10
    sensitivity = "RESTRICTED_HR"
    fact_type = FactType.TRAINING_COMPLETION
    title = "培训完成（HR10 已核验事实）"
    quantitative_field = "verified_hours"


class AcademicTeachingProvider(HrEvidenceProvider):
    provider_key = "ACADEMIC_TEACHING"
    owner_domain = "academic"
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
            message="教务系统对接尚未配置。教学任务/课时/评价事实将在对接完成后提供。",
        )
