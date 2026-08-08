"""
hr_structure/services/effective_runner.py

EffectiveRunner —— 生效执行器（总册 14.9 / 24.3 失效事件）。

- 扫描 SCHEDULED 且到期的 change case；
- 幂等 execution key；
- 失败可重试、可观测；
- 生效后写审计（简化：写入 execution_result_json）。
"""

from __future__ import annotations

import logging
from datetime import date

from django.db import transaction

from hr_structure.models import HrStructureChangeCase
from hr_structure.services.reorganization import ReorganizationService

logger = logging.getLogger(__name__)


def run_effective_runner(tenant_id=None, as_of=None):
    """执行到期的 SCHEDULED case。返回处理结果摘要。"""
    from hr_structure.services.reorganization import find_scheduled_cases

    as_of = as_of or date.today()
    cases = find_scheduled_cases(tenant_id, as_of=as_of) if tenant_id else (
        HrStructureChangeCase.objects.filter(
            status=HrStructureChangeCase.Status.SCHEDULED,
            requested_effective_date__lte=as_of,
        )
    )
    results = {"processed": 0, "effective": 0, "failed": 0}
    for case in cases:
        try:
            scope = type("S", (), {"tenant_id": case.tenant_id})()
            svc = ReorganizationService(scope, actor="effective-runner")
            with transaction.atomic():
                executed = svc.execute_effective(
                    case,
                    execution_key=f"eff-{case.case_no}-{case.requested_effective_date}",
                )
            results["processed"] += 1
            if executed.status == HrStructureChangeCase.Status.EFFECTIVE:
                results["effective"] += 1
        except Exception as exc:  # 失败可重试，不吞
            results["failed"] += 1
            logger.error("effective runner failed case=%s: %s", case.case_no, exc)
    return results
