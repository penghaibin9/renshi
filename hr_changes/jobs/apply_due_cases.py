"""
hr_changes/jobs/apply_due_cases.py —— 到期生效调度（S8，总册 §48/§11）。

find due cases（APPROVED_WAITING_EFFECTIVE 且到期）
→ lock
→ revalidate（ApplyService 内完成）
→ apply
逐 case 独立事务；失败进入 APPLY_FAILED 可重试，不影响其他案件。
"""

from __future__ import annotations

from datetime import date

from hr_changes.constants import CaseStatus
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.services.apply_service import ApplyService


def run_due_applications(*, tenant_id: int = None) -> dict:
    """处理全部到期案件；返回 {total, applied, failed}。"""
    due_qs = HrPersonnelChangeCase.objects.filter(
        status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
        requested_effective_at__lte=date.today(),
    )
    if tenant_id:
        due_qs = due_qs.filter(tenant_id=tenant_id)
    cases = list(due_qs.select_for_update().order_by("requested_effective_at"))

    total = len(cases)
    applied = 0
    failed = 0
    for case in cases:
        result = ApplyService(case.tenant_id).apply_case(case.id)
        if result.status == CaseStatus.EFFECTIVE:
            applied += 1
        else:
            failed += 1
    return {"total": total, "applied": applied, "failed": failed}
