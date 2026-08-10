"""HR09 对 Horilla 旧 qualification 字段的只读证据适配器。

旧 Employee.qualification 只能作为迁移线索，永远不能直接变成 VERIFIED 教师资格事实。
适配器显式 tenant 过滤，不依赖 Horilla request thread-local manager。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)


class HorillaLegacyQualificationProvider(HrEvidenceProvider):
    provider_key = "LEGACY_HORILLA_QUALIFICATION"
    owner_domain = "legacy:employee"
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
        if staff_master_id is None:
            return ProviderEvidenceResult.not_applicable(provider_version="0.1.0-legacy")

        from employee.models import Employee
        from hr_staff.models import HrStaffMaster

        legacy_employee_id = (
            HrStaffMaster.objects.filter(
                tenant_id=tenant_id,
                id=staff_master_id,
            )
            .values_list("legacy_employee_id", flat=True)
            .first()
        )
        if not legacy_employee_id:
            return ProviderEvidenceResult.not_applicable(provider_version="0.1.0-legacy")

        legacy_employee = Employee.objects.filter(
            id=legacy_employee_id,
            employee_work_info__company_id_id=tenant_id,
        ).first()
        if legacy_employee is None:
            return ProviderEvidenceResult.unavailable(
                "HR09_LEGACY_EMPLOYEE_NOT_FOUND",
                "legacy employee link does not resolve inside the requested tenant",
                provider_version="0.1.0-legacy",
            )

        qualification = (getattr(legacy_employee, "qualification", "") or "").strip()
        if not qualification:
            return ProviderEvidenceResult.not_applicable(provider_version="0.1.0-legacy")

        item = ProviderEvidenceItem(
            source_domain="LEGACY_HORILLA_EMPLOYEE",
            source_object_type="Employee.qualification",
            source_object_id=str(legacy_employee_id),
            title=qualification,
            verification_status="MIGRATED_UNVERIFIED",
            snapshot_json={
                "legacyEmployeeId": legacy_employee_id,
                "sourceField": "employee.Employee.qualification",
                "trustLevel": "MIGRATED_UNVERIFIED",
                "authority": False,
            },
        )
        return ProviderEvidenceResult.ok(
            items=[item],
            source_updated_at=datetime.now(timezone.utc),
            provider_version="0.1.0-legacy",
        )
