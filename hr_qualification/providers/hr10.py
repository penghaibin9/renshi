"""
hr_qualification/providers/hr10.py —— HR10 培训/企业实践 Provider（占位 · 总册 §166）。

HR10 未就绪时返回 UNAVAILABLE（≠ 0 ≠ false），禁止假设为 0。
"""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.providers.base import HrEvidenceProvider, ProviderEvidenceResult


class Hr10EnterprisePracticeProvider(HrEvidenceProvider):
    provider_key = "HR10_ENTERPRISE_PRACTICE"
    owner_domain = "hr_development"
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
            reason_code="MODULE_NOT_READY",
            message="HR10 培训进修与企业实践模块尚未交付。企业实践/培训事实将在 HR10 VERIFIED 后提供。",
        )


class Hr10TrainingProvider(HrEvidenceProvider):
    provider_key = "HR10_TRAINING"
    owner_domain = "hr_development"
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
            reason_code="MODULE_NOT_READY",
            message="HR10 培训进修与企业实践模块尚未交付。",
        )


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
