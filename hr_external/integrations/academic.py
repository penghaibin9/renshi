"""
hr_external/integrations/academic.py —— 教务系统 Provider（S2，总册 §11/§48/§96/§97）。

# [总控占位] 数字校园/教务系统未接入。
- 当前返回 UNAVAILABLE（禁止 mock 冒充真实对接，00 §69）。
- 替换时机：真实教务接口/数据交换接入后，实现 teacher identity 下发与课程任务回传。

契约：
  activate_teacher_identity(*, tenant_id, external_teacher_no, academic_teacher_id, valid_from, valid_to)
  deactivate_teacher_identity(*, tenant_id, academic_teacher_id)
  fetch_teaching_assignments(*, tenant_id, academic_teacher_id, term)
  幂等键：调用方传 idempotency_key；webhook 重复按 providerEventId 去重。
"""

from __future__ import annotations

from typing import Optional

from hr_external.integrations.base import BaseProvider, ProviderResult


class AcademicProvider(BaseProvider):
    owner_domain = "ACADEMIC"
    sensitivity = "INTERNAL"

    def activate_teacher_identity(
        self,
        *,
        tenant_id: int,
        external_teacher_no: str,
        academic_teacher_id: str,
        valid_from: str,
        valid_to: Optional[str],
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] 教务未接入：返回 UNAVAILABLE。替换为真实下发（异步 provisioning + reconciliation）。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "Academic system not integrated yet",
        )

    def deactivate_teacher_identity(
        self,
        *,
        tenant_id: int,
        academic_teacher_id: str,
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] 教务未接入：返回 UNAVAILABLE。替换为真实停用（保留历史课程事实）。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "Academic system not integrated yet",
        )

    def fetch_teaching_assignments(
        self, *, tenant_id: int, academic_teacher_id: str, term: str
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        # [总控占位] 教务未接入：返回 UNAVAILABLE。替换为课程/班级/学期/学时回传。
        return self.unavailable(
            "PROVIDER_UNAVAILABLE",
            "Academic system not integrated yet",
        )
