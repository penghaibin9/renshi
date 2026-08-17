"""
hr_changes/services/rebase_service.py —— 未来事件冲突/Rebase（总册 §12）。

- check：检测同人未来生效案件之间的冲突；
  - NO_CONFLICT：无重叠；
  - REBASE_REQUIRED：存在 base_snapshot_version 过期的 future 案件（需重算后仍可共存）；
  - HARD_CONFLICT：两个 future 案件同一天/重叠区间改变同一主岗 → 不能静默生效。
- 禁止静默用旧快照生效。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from hr_changes.constants import CaseStatus, FutureConflictResult
from hr_changes.models import HrPersonnelChangeCase


class RebaseService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def check(self, case: HrPersonnelChangeCase, effective_at: Optional[date] = None) -> str:
        """检测同人其他未来/已生效案件与本案的冲突。"""
        effective_at = effective_at or (case.approved_effective_at or case.requested_effective_at)

        # 目标岗位冲突：另一个 APPROVED_WAITING_EFFECTIVE/APPLYING/EFFECTIVE 案件
        # 在相同生效日或更早生效日已占用同一主岗变更方向 → HARD_CONFLICT
        if case.target_position_id_id:
            conflict = (
                HrPersonnelChangeCase.objects.filter(
                    tenant_id=self.tenant_id,
                    staff_master_id=case.staff_master_id,
                    target_position_id=case.target_position_id,
                    status__in=(
                        CaseStatus.APPROVED_WAITING_EFFECTIVE,
                        CaseStatus.APPLYING,
                        CaseStatus.EFFECTIVE,
                    ),
                    requested_effective_at__lte=effective_at,
                )
                .exclude(id=case.id)
                .exists()
            )
            if conflict:
                return FutureConflictResult.HARD_CONFLICT

        # 同人同生效日两个主岗变更案件 → HARD_CONFLICT
        same_day = (
            HrPersonnelChangeCase.objects.filter(
                tenant_id=self.tenant_id,
                staff_master_id=case.staff_master_id,
                requested_effective_at=effective_at,
                status__in=(
                    CaseStatus.APPROVED_WAITING_EFFECTIVE,
                    CaseStatus.APPLYING,
                ),
            )
            .exclude(id=case.id)
            .exists()
        )
        if same_day:
            return FutureConflictResult.HARD_CONFLICT

        # 存在 base snapshot 过期（版本落后于当前案件）→ REBASE_REQUIRED
        stale = (
            HrPersonnelChangeCase.objects.filter(
                tenant_id=self.tenant_id,
                staff_master_id=case.staff_master_id,
                requested_effective_at__gt=effective_at,
                status__in=(CaseStatus.APPROVED_WAITING_EFFECTIVE, CaseStatus.DRAFT),
                base_effective_at__lt=effective_at,
            )
            .exclude(id=case.id)
            .exists()
        )
        if stale:
            return FutureConflictResult.REBASE_REQUIRED

        return FutureConflictResult.NO_CONFLICT
