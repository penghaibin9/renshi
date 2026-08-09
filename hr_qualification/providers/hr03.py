"""
hr_qualification/providers/hr03.py —— HR03 教育/学位/工作经历 Provider（总册 §166）。

消费 HR03 已交付的权威模型，输出双师证据。
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
    from hr_staff.models import (
        HrDegreeRecord,
        HrEducationExperience,
        HrWorkExperience,
    )

    _HR03_READY = True
except ImportError:
    _HR03_READY = False


class Hr03EducationProvider(HrEvidenceProvider):
    provider_key = "HR03_EDUCATION"
    owner_domain = "hr_staff"
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
        if not _HR03_READY or staff_master_id is None:
            return ProviderEvidenceResult.not_applicable()

        items: list[ProviderEvidenceItem] = []
        now = datetime.now(timezone.utc)

        qs = HrEducationExperience.objects.filter(
            tenant_id=tenant_id, staff_id=staff_master_id
        )
        for edu in qs:
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR03_EDUCATION",
                    source_object_type="HrEducationExperience",
                    source_object_id=str(edu.id),
                    evidence_date=edu.end_date,
                    title=f"{edu.education_level} {edu.major_name} ({edu.school_name})",
                    verification_status=edu.verification_status,
                )
            )

        qs_deg = HrDegreeRecord.objects.filter(
            tenant_id=tenant_id, staff_id=staff_master_id
        )
        for deg in qs_deg:
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR03_DEGREE",
                    source_object_type="HrDegreeRecord",
                    source_object_id=str(deg.id),
                    evidence_date=deg.awarded_date,
                    title=f"{deg.degree_level} {deg.degree_name} ({deg.granting_institution})",
                    verification_status=deg.verification_status,
                )
            )

        return ProviderEvidenceResult.ok(items=items, source_updated_at=now)


class Hr03WorkHistoryProvider(HrEvidenceProvider):
    provider_key = "HR03_WORK_HISTORY"
    owner_domain = "hr_staff"
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
        if not _HR03_READY or staff_master_id is None:
            return ProviderEvidenceResult.not_applicable()

        items: list[ProviderEvidenceItem] = []
        now = datetime.now(timezone.utc)

        qs = HrWorkExperience.objects.filter(
            tenant_id=tenant_id, staff_id=staff_master_id
        )
        for work in qs:
            duration_days = None
            if work.start_date and work.end_date:
                duration_days = (work.end_date - work.start_date).days

            items.append(
                ProviderEvidenceItem(
                    source_domain="HR03_WORK_HISTORY",
                    source_object_type="HrWorkExperience",
                    source_object_id=str(work.id),
                    evidence_date=work.start_date,
                    title=f"{work.organization_name} · {work.position_title}",
                    role=work.experience_type,
                    quantitative_value=float(duration_days) if duration_days else None,
                    verification_status=work.verification_status,
                )
            )

        return ProviderEvidenceResult.ok(items=items, source_updated_at=now)
