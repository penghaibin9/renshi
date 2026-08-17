"""
hr_qualification/providers/hr08.py —— HR08 外聘教师 eligibility Provider。

总册 §14：正式外聘教师可按国家/地方制度参照双师认定。
HR08 已交付 → 读取 HrExternalEngagement，输出 eligibility 证据。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from django.utils import timezone

from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

try:
    from hr_external.models import HrExternalEngagement

    _HR08_READY = True
except ImportError:
    _HR08_READY = False


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
        if not _HR08_READY:
            return ProviderEvidenceResult.unavailable(
                reason_code="HR08_NOT_READY",
                message="HR08 兼职外聘教师模块尚未就绪。",
            )

        now = datetime.now(timezone.utc)
        items: list[ProviderEvidenceItem] = []

        engagements = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id,
            person_id=person_id,
            status__in=("ACTIVE", "DRAFT"),
        )

        for eng in engagements:
            duration_days = None
            if eng.start_at:
                end = eng.end_at or as_of
                duration_days = (end - eng.start_at).days

            items.append(
                ProviderEvidenceItem(
                    source_domain="HR08_ENGAGEMENT",
                    source_object_type="HrExternalEngagement",
                    source_object_id=str(eng.id),
                    evidence_date=eng.start_at,
                    title=f"External Engagement #{eng.engagement_no}",
                    role=eng.category_id.name if eng.category_id_id else "External",
                    quantitative_value=float(duration_days) if duration_days else None,
                    verification_status="VERIFIED" if eng.status == "ACTIVE" else "UNVERIFIED",
                )
            )

        if not items:
            return ProviderEvidenceResult.not_applicable()

        return ProviderEvidenceResult.ok(items=items, source_updated_at=now)
