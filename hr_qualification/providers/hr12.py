"""
hr_qualification/providers/hr12.py —— HR12 考核结果 Provider（占位 · 总册 §166）。

HR12 未就绪时返回 UNAVAILABLE（≠ 0 ≠ false）。
"""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.providers.base import HrEvidenceProvider, ProviderEvidenceResult


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
        return ProviderEvidenceResult.unavailable(
            reason_code="MODULE_NOT_READY",
            message="HR12 年度与聘期考核模块尚未交付。考核结果将在 HR12 VERIFIED 后提供。",
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
