"""HR10 verified development-fact providers for HR09 evidence evaluation."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from django.db.models import Q

from hr10_development.constants import FactType, VerificationStatus
from hr10_development.models.development_fact import HrDevelopmentFact
from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)
from hr_staff.models import HrStaffMaster

PROVIDER_VERSION = "hr10-development-fact-v1"
TRUSTED_VERIFICATION_STATUSES = {
    VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
    VerificationStatus.TRAINING_PROVIDER_VERIFIED,
    VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
    VerificationStatus.HR_VERIFIED,
    VerificationStatus.DOCUMENT_VERIFIED,
    VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
    VerificationStatus.MIGRATED_VERIFIED,
}


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _resolve_legacy_staff_id(
    *, person_id: uuid.UUID, staff_master_id: uuid.UUID | None, tenant_id: int
) -> int | None:
    """Resolve HR10's legacy bigint staff key through canonical HR03 identity."""
    qs = HrStaffMaster.objects.filter(tenant_id=tenant_id, person_id=person_id)
    if staff_master_id is not None:
        qs = qs.filter(id=staff_master_id)
    staff = qs.only("legacy_employee_id").first()
    if staff is None or staff.legacy_employee_id is None:
        return None
    return int(staff.legacy_employee_id)


def _verified_facts_as_of(
    *, tenant_id: int, legacy_staff_id: int, fact_type: str, as_of: date
):
    facts = HrDevelopmentFact.objects.filter(
        tenant_id=tenant_id,
        staff_master_id=legacy_staff_id,
        fact_type=fact_type,
        verification_status__in=TRUSTED_VERIFICATION_STATUSES,
        valid_from__isnull=False,
        valid_from__lte=as_of,
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=as_of))

    # Facts are append-only. A trusted successor that is already effective at
    # this as-of boundary suppresses its predecessor, while future successors
    # do not hide historical evidence.
    superseded_ids = facts.exclude(supersedes_fact_id__isnull=True).values_list(
        "supersedes_fact_id", flat=True
    )
    return facts.exclude(id__in=superseded_ids).order_by("valid_from", "id")


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
        if source_version and source_version != PROVIDER_VERSION:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_VERSION_UNSUPPORTED",
                message=(
                    f"Requested HR10 source version {source_version!r} is not "
                    f"available; current provider is {PROVIDER_VERSION}."
                ),
                provider_version=PROVIDER_VERSION,
            )

        legacy_staff_id = _resolve_legacy_staff_id(
            person_id=person_id,
            staff_master_id=staff_master_id,
            tenant_id=tenant_id,
        )
        if legacy_staff_id is None:
            return ProviderEvidenceResult.unavailable(
                reason_code="SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
                message=(
                    "Canonical HR03 StaffMaster is missing a tenant-scoped "
                    "legacy employee mapping required by the current HR10 fact store."
                ),
                provider_version=PROVIDER_VERSION,
            )

        facts = list(
            _verified_facts_as_of(
                tenant_id=tenant_id,
                legacy_staff_id=legacy_staff_id,
                fact_type=self.fact_type,
                as_of=as_of,
            )
        )
        items = []
        for fact in facts:
            quantitative = getattr(fact, self.quantitative_field, None)
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR10",
                    source_object_type="HrDevelopmentFact",
                    source_object_id=str(fact.id),
                    evidence_date=fact.end_date or fact.valid_from or fact.start_date,
                    title=self.title,
                    role=fact.activity_type or "",
                    quantitative_value=(
                        float(quantitative) if quantitative is not None else None
                    ),
                    verification_status=fact.verification_status,
                    snapshot_json={
                        "factType": fact.fact_type,
                        "activityType": fact.activity_type,
                        "verifiedHours": _decimal_text(fact.verified_hours),
                        "verifiedDays": fact.verified_days,
                        "verifiedCredits": _decimal_text(fact.verified_credits),
                        "levelOrResult": fact.level_or_result,
                        "validFrom": fact.valid_from.isoformat()
                        if fact.valid_from
                        else None,
                        "validTo": fact.valid_to.isoformat() if fact.valid_to else None,
                        "evidencePackageHash": fact.evidence_package_hash,
                    },
                )
            )

        source_updated_at = max((fact.updated_at for fact in facts), default=None)
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
