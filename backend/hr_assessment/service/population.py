"""HR12 — S3 补齐：Population Freeze 服务 + Cycle 生命周期管理员。"""

from __future__ import annotations

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.cycle import HrAssessmentCycle, HrAssessmentPopulationSnapshot


class PopulationFreezeService:
    """冻结考核人群 — 从 ACTIVE 过渡到 POPULATION_FREEZING → 生成快照 → 进入 ACTIVE。"""

    @transaction.atomic
    def freeze_population(self, cycle: HrAssessmentCycle, staff_data: list[dict]) -> list[HrAssessmentPopulationSnapshot]:
        if cycle.lifecycle_status not in ("PUBLISHED", "POPULATION_FREEZING", "ACTIVE"):
            raise ValidationError(_(f"当前周期状态 {cycle.lifecycle_status} 不允许冻结人群"))

        cycle.lifecycle_status = "POPULATION_FREEZING"
        cycle.save(update_fields=["lifecycle_status"])

        snapshots = []
        for data in staff_data:
            snap = HrAssessmentPopulationSnapshot.objects.create(
                tenant_id=cycle.tenant_id,
                cycle=cycle,
                staff_id=data["staff_id"],
                included=data.get("included", True),
                org_id=data.get("org_id"),
                position_id=data.get("position_id"),
                worker_category=data.get("worker_category", ""),
                classification_profile_json=data.get("classification_profile_json", {}),
                snapshot_at=cycle.start_at,
                policy_version_id=data.get("policy_version_id"),
            )
            snapshots.append(snap)

        cycle.lifecycle_status = "ACTIVE"
        cycle.save(update_fields=["lifecycle_status"])
        return snapshots

    def add_to_population(self, cycle: HrAssessmentCycle, staff_id, **kwargs) -> HrAssessmentPopulationSnapshot:
        return HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=cycle.tenant_id, cycle=cycle, staff_id=staff_id,
            included=True, snapshot_at=cycle.start_at, **kwargs,
        )

    def exclude_from_population(self, cycle: HrAssessmentCycle, staff_id, reason: str) -> None:
        HrAssessmentPopulationSnapshot.objects.filter(
            cycle=cycle, staff_id=staff_id,
        ).update(included=False, excluded=True, special_case=reason)


class CycleLifecycleService:
    """周期生命周期管理 — DRAFT→VALIDATING→...→CLOSED。"""

    ALLOWED_TRANSITIONS = {
        "DRAFT": ["VALIDATING"],
        "VALIDATING": ["READY_TO_PUBLISH", "DRAFT"],
        "READY_TO_PUBLISH": ["PUBLISHED", "DRAFT"],
        "PUBLISHED": ["POPULATION_FREEZING", "ACTIVE"],
        "POPULATION_FREEZING": ["ACTIVE", "PUBLISHED"],
        "ACTIVE": ["FINALIZING", "SUSPENDED"],
        "FINALIZING": ["CLOSED", "ACTIVE"],
        "CLOSED": ["ARCHIVED", "REOPENED_BY_AUTHORITY"],
        "ARCHIVED": [],
        "SUSPENDED": ["ACTIVE", "CANCELLED"],
        "CANCELLED": [],
        "REOPENED_BY_AUTHORITY": ["ACTIVE"],
    }

    @transaction.atomic
    def transition(self, cycle: HrAssessmentCycle, to_status: str) -> HrAssessmentCycle:
        allowed = self.ALLOWED_TRANSITIONS.get(cycle.lifecycle_status, [])
        if to_status not in allowed:
            raise ValidationError(
                _(f"不允许从 {cycle.lifecycle_status} 转换到 {to_status}")
            )
        cycle.lifecycle_status = to_status
        cycle.save(update_fields=["lifecycle_status"])
        return cycle
