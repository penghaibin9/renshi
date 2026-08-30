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

from django.utils import timezone

from hr_changes.constants import CaseStatus
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.services.apply_service import ApplyService


def run_due_applications(
    *, tenant_id: int, as_of: date = None, actor_user_id=None, dry_run: bool = False
) -> dict:
    """Process one tenant only; callers may supply a frozen business date."""
    if not tenant_id:
        raise ValueError("TENANT_CONTEXT_REQUIRED")
    as_of = as_of or timezone.localdate()
    if type(as_of) is not date:
        raise ValueError("CHANGE_EFFECTIVE_DATE_INVALID")
    due_qs = HrPersonnelChangeCase.objects.filter(
        tenant_id=tenant_id,
        status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
        requested_effective_at__lte=as_of,
    )
    cases = list(due_qs.order_by("requested_effective_at", "id"))

    total = len(cases)
    if dry_run:
        return {
            "tenantId": tenant_id,
            "asOf": as_of.isoformat(),
            "dryRun": True,
            "total": total,
            "applied": 0,
            "failed": 0,
        }
    applied = 0
    failed = 0
    for case in cases:
        result = ApplyService(
            tenant_id,
            actor_user_id=actor_user_id,
        ).apply_case(
            case.id,
            as_of=as_of,
            request_id=f"hr06-due:{tenant_id}:{case.id}",
        )
        if result.status == CaseStatus.EFFECTIVE:
            applied += 1
        else:
            failed += 1
    return {
        "tenantId": tenant_id,
        "asOf": as_of.isoformat(),
        "dryRun": False,
        "total": total,
        "applied": applied,
        "failed": failed,
    }
