"""
hr10_development/providers/qualification_provider.py

HR09 Evidence Provider 实现。

HR10 → HR09：只返回 VERIFIED DevelopmentFact 作为双师认定证据。
这是 HR10 最重要的跨域 Provider 契约（总册 §115）。
"""

from datetime import date

from django.db.models import Q

from hr10_development.providers.base import (
    QualificationEvidenceProvider,
    ProviderResult,
    ProviderStatus,
)
from hr10_development.constants import VerificationStatus


class Hr09QualificationEvidenceProvider(QualificationEvidenceProvider):
    """HR09 双师证据 Provider — 只输出 VERIFIED facts。"""

    def get_evidence(
        self,
        staff_master_id: str,
        tenant_id: int,
        as_of: date | None = None,
        fact_types: list[str] | None = None,
    ) -> ProviderResult:
        from hr10_development.models.development_fact import HrDevelopmentFact

        VERIFIED_STATUSES = [
            VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
            VerificationStatus.TRAINING_PROVIDER_VERIFIED,
            VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
            VerificationStatus.HR_VERIFIED,
            VerificationStatus.DOCUMENT_VERIFIED,
            VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
        ]

        qs = HrDevelopmentFact.objects.effective().filter(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            verification_status__in=VERIFIED_STATUSES,
        )

        if fact_types:
            qs = qs.filter(fact_type__in=fact_types)

        if as_of:
            qs = qs.filter(valid_from__lte=as_of).filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=as_of)
            )

        evidence_list = []
        for f in qs.order_by("-valid_from")[:200]:
            evidence_list.append({
                "sourceFactId": str(f.id),
                "factType": f.fact_type,
                "verifiedStatus": f.verification_status,
                "period": {"from": str(f.start_date) if f.start_date else None,
                           "to": str(f.end_date) if f.end_date else None},
                "provider": {"id": f.provider_org_id},
                "verifiedDuration": {
                    "hours": float(f.verified_hours) if f.verified_hours else 0,
                    "days": f.verified_days or 0,
                },
                "evidencePackageHash": f.evidence_package_hash,
                "sourceUpdatedAt": f.updated_at.isoformat(),
            })

        return ProviderResult(
            status=ProviderStatus.OK,
            data=evidence_list,
            source_updated_at=qs.order_by("-updated_at").first().updated_at if evidence_list else None,
        )
