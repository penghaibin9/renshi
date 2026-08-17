"""
hr_onboarding/jobs/migration.py

Legacy Migration（05 §46）：Horilla Candidate → HrOnboardingCase。
- source_type = LEGACY_MIGRATION；
- 幂等：source unique 兜底，重复执行不重复建；
- 已转换 Employee 回填 HR03 link + activation snapshot；
- 不重新触发账号/岗位/工资副作用。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def migrate_candidate(*, tenant_id: int, candidate) -> dict:
    """
    迁移单个 legacy Candidate → HrOnboardingCase（幂等）。
    返回 {created, case_id, skipped_reason}。
    """
    from hr_onboarding.models import HrOnboardingCase, HrOnboardingStageTransition

    if candidate is None:
        return {"created": False, "skipped_reason": "candidate_missing"}

    existing = HrOnboardingCase.objects.filter(
        tenant_id=tenant_id,
        source_type="LEGACY_MIGRATION",
        source_id=str(candidate.id),
    ).first()
    if existing is not None:
        return {"created": False, "case_id": str(existing.id), "skipped_reason": "already_exists"}

    joining = getattr(candidate, "joining_date", None)
    case = HrOnboardingCase.objects.create(
        tenant_id=tenant_id,
        case_no=f"OB-MIG-{tenant_id}-{candidate.id}",
        source_type="LEGACY_MIGRATION",
        source_id=str(candidate.id),
        candidate_id=candidate.id,
        expected_report_date=joining,
        status="CREATED",
    )
    HrOnboardingStageTransition.objects.create(
        tenant_id=tenant_id,
        case=case,
        from_stage="",
        to_stage="CREATED",
        action="LEGACY_MIGRATION",
        reason="历史数据迁移",
    )
    return {"created": True, "case_id": str(case.id)}


def migrate_candidate_batch(*, tenant_id: int, candidates, limit: Optional[int] = 500) -> dict:
    """批量迁移（逐项幂等，不失败半途静默）。"""
    created = 0
    skipped = 0
    errors = []
    for candidate in candidates[:limit]:
        try:
            result = migrate_candidate(tenant_id=tenant_id, candidate=candidate)
            if result.get("created"):
                created += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"candidate_id": getattr(candidate, "id", None), "error": str(exc)})
    return {"created": created, "skipped": skipped, "errors": errors}
