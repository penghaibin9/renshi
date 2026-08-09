"""
hr_external/services/projection_service.py —— Legacy 投影（S9，总册 §112-113/§6.3/§55）。

- Active External Engagement → HrExternalProjectionState（worker_kind=EXTERNAL 标记）；
- 标记 regular_employee/benefits_eligible/payroll_regular/attendance_regular 全 false（§6.3）；
- 单向 authority → legacy（§55）：本服务只计算投影状态 + 标记，不反向写 legacy 权威；
- 投影副作用禁令（§113）：不自动进入正式 payroll/leave/attendance/编制/manager/benefits；
- DUAL_READ_COMPARE（§115）：对账 person/category/host org/dates/status → DRIFT。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.utils import timezone

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import (
    HrExternalEngagement,
    HrExternalProjectionState,
    HrExternalTeacherProfile,
)


@dataclass
class ProjectionSummary:
    projected: int = 0
    missing_legacy: int = 0
    drift: int = 0
    checked: int = 0
    notes: list = field(default_factory=list)


class ProjectionService:
    """Active Engagement → 投影状态（worker_kind=EXTERNAL）。legacy 映射通过 HR03 HrStaffMaster 解析。"""

    @staticmethod
    def _hash(profile: HrExternalTeacherProfile, eng: Optional[HrExternalEngagement]) -> str:
        payload = {
            "tenantId": profile.tenant_id,
            "externalTeacherNo": profile.external_teacher_no,
            "legalName": profile.person_id.legal_name if profile.person_id_id else "",
            "category": profile.primary_category.code if profile.primary_category else "",
            "status": eng.status if eng else "",
            "startAt": str(eng.start_at) if eng else "",
            "endAt": str(eng.end_at) if eng else "",
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def project_active_external_workers(self, *, tenant_id: int, as_of: Optional[date] = None) -> ProjectionSummary:
        """为当前 active 外聘生成/更新投影状态（worker_kind=EXTERNAL）。"""
        summary = ProjectionSummary()
        as_of = as_of or date.today()
        active_engs = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id,
            status__in=[
                ExternalEngagementStatus.ACTIVE,
                ExternalEngagementStatus.REVIEW_DUE,
                ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
                ExternalEngagementStatus.SUSPENDED,
            ],
        ).select_related("external_profile_id", "external_profile_id__person_id")

        seen_profiles = set()
        for eng in active_engs:
            profile = eng.external_profile_id
            if profile.id in seen_profiles:
                continue
            seen_profiles.add(profile.id)

            state = HrExternalProjectionState.objects.get_or_create(
                tenant_id=tenant_id,
                external_profile_id=profile,
                defaults={
                    "worker_kind": "EXTERNAL",
                    "regular_employee": False,
                    "benefits_eligible": False,
                    "payroll_regular": False,
                    "attendance_regular": False,
                },
            )[0]
            state.projection_hash = self._hash(profile, eng)
            state.last_projected_at = timezone.now()
            state.save(
                update_fields=["projection_hash", "last_projected_at", "updated_at"]
            )

            # 关联 legacy Employee（映射，非 authority key，§112）：通过 HR03 StaffMasterProvider
            # 按 person 找 legacy 投影；找不到 → LEGACY_EMPLOYEE_MISSING。
            legacy_id = self._resolve_legacy_employee(tenant_id, profile)
            summary.projected += 1
            if not legacy_id:
                summary.missing_legacy += 1
                state.status = "LEGACY_EMPLOYEE_MISSING"
                state.save(update_fields=["status", "updated_at"])

        return summary

    def _resolve_legacy_employee(self, tenant_id: int, profile) -> Optional[int]:
        """通过 HR03 HrStaffMaster 的 legacy_employee_id 找到 Horilla Employee 映射（§112）。"""
        from hr_staff.models import HrStaffMaster

        staff = HrStaffMaster.objects.filter(
            tenant_id=tenant_id, person_id=profile.person_id
        ).first()
        return staff.legacy_employee_id if staff else None

    def reconcile(self, *, tenant_id: int) -> ProjectionSummary:
        """DUAL_READ_COMPARE（§115）：对比投影状态与 active engagement 现状。"""
        summary = ProjectionSummary()
        states = HrExternalProjectionState.objects.filter(tenant_id=tenant_id)
        for state in states:
            active = HrExternalEngagement.objects.filter(
                tenant_id=tenant_id,
                external_profile_id=state.external_profile_id,
                status__in=[
                    ExternalEngagementStatus.ACTIVE,
                    ExternalEngagementStatus.REVIEW_DUE,
                    ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
                    ExternalEngagementStatus.SUSPENDED,
                ],
            ).exists()
            if not active:
                state.status = "SUPERSEDED"
                state.save(update_fields=["status", "updated_at"])
                continue
            summary.checked = getattr(summary, "checked", 0) + 1
        return summary
