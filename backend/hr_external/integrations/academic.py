"""
hr_external/integrations/academic.py —— 教务系统 Provider（S2，总册 §11/§48/§96/§97）。

生产接入由 ``HR08_ACADEMIC_PROVIDER`` 配置提供 BASE_URL、TOKEN、TIMEOUT_MS。
缺配置返回 UNAVAILABLE；写调用必须携带幂等键且成功响应必须包含 receiptId。

契约：
  activate_teacher_identity(*, tenant_id, external_teacher_no, academic_teacher_id, valid_from, valid_to)
  deactivate_teacher_identity(*, tenant_id, external_teacher_no, academic_teacher_id)
  fetch_teaching_assignments(*, tenant_id, academic_teacher_id, term)
  幂等键：调用方传 idempotency_key；服务端重复请求返回同一业务回执。
"""

from __future__ import annotations

from typing import Optional

from hr_external.integrations.base import ProviderResult
from hr_external.integrations.http import ConfiguredJsonProvider


class AcademicProvider(ConfiguredJsonProvider):
    owner_domain = "ACADEMIC"
    sensitivity = "INTERNAL"
    settings_name = "HR08_ACADEMIC_PROVIDER"

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
        return self._request(
            tenant_id=tenant_id,
            method="POST",
            path="teacher-identities/activate",
            idempotency_key=idempotency_key,
            payload={
                "externalTeacherNo": external_teacher_no,
                "academicTeacherId": academic_teacher_id,
                "validFrom": valid_from,
                "validTo": valid_to,
            },
            receipt_required=True,
        )

    def deactivate_teacher_identity(
        self,
        *,
        tenant_id: int,
        academic_teacher_id: str,
        external_teacher_no: str = "",
        idempotency_key: str = "",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        return self._request(
            tenant_id=tenant_id,
            method="POST",
            path="teacher-identities/deactivate",
            idempotency_key=idempotency_key,
            payload={
                "academicTeacherId": academic_teacher_id,
                "externalTeacherNo": external_teacher_no,
            },
            receipt_required=True,
        )

    def fetch_teaching_assignments(
        self, *, tenant_id: int, academic_teacher_id: str, term: str
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        return self._request(
            tenant_id=tenant_id,
            method="GET",
            path="teaching-assignments",
            params={"academicTeacherId": academic_teacher_id, "term": term},
        )
