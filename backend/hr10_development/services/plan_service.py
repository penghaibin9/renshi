"""
hr10_development/services/plan_service.py

发展计划领域服务。
Plan CRUD + lifecycle transitions + state machine enforcement。
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr10_development.constants import PlanLifecycleStatus, PlanVersionStatus
from hr10_development.models.plan import HrDevelopmentPlan
from hr10_development.models.plan_version import HrDevelopmentPlanVersion


class PlanService:
    """发展计划生命周期服务。"""

    @staticmethod
    def create_plan(
        tenant_id: int,
        plan_no: str,
        plan_type: str,
        start_date,
        end_date,
        cycle_type: str = "ANNUAL",
        owner_org_id: Optional[int] = None,
        staff_master_id: Optional[int] = None,
        created_by=None,
    ) -> HrDevelopmentPlan:
        plan = HrDevelopmentPlan.objects.create(
            tenant_id=tenant_id,
            plan_no=plan_no,
            plan_type=plan_type,
            owner_org_id=owner_org_id,
            staff_master_id=staff_master_id,
            cycle_type=cycle_type,
            start_date=start_date,
            end_date=end_date,
            created_by=created_by,
            updated_by=created_by,
        )
        return plan

    @staticmethod
    def transition(
        plan: HrDevelopmentPlan,
        target: PlanLifecycleStatus,
        actor=None,
    ) -> bool:
        if not plan.can_transition_to(target):
            return False
        old_status = plan.lifecycle_status
        plan.lifecycle_status = target
        if target == PlanLifecycleStatus.APPROVED:
            plan.approved_at = timezone.now()
        elif target == PlanLifecycleStatus.PUBLISHED:
            plan.published_at = timezone.now()
        plan.updated_by = actor
        plan.version = plan.version + 1
        plan.save(update_fields=[
            "lifecycle_status", "approved_at", "published_at", "version", "updated_by", "updated_at"
        ])
        return True

    @staticmethod
    @transaction.atomic
    def create_version(
        plan: HrDevelopmentPlan,
        objectives_json: dict,
        population_snapshot: dict,
        budget_snapshot: dict,
        policy_snapshot: dict,
        target_snapshot: dict,
        effective_from=None,
        created_by=None,
    ) -> HrDevelopmentPlanVersion:
        latest = (
            HrDevelopmentPlanVersion.objects
            .filter(plan_id=plan.id)
            .order_by("-version_no")
            .first()
        )
        next_no = (latest.version_no + 1) if latest else 1

        # Compute content hash over all snapshot fields
        hash_input = json.dumps({
            "objectives": objectives_json,
            "population": population_snapshot,
            "budget": budget_snapshot,
            "policy": policy_snapshot,
            "target": target_snapshot,
        }, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        version = HrDevelopmentPlanVersion.objects.create(
            tenant_id=plan.tenant_id,
            plan_id=plan.id,
            version_no=next_no,
            status=PlanVersionStatus.DRAFT,
            objectives_json=objectives_json,
            population_snapshot_json=population_snapshot,
            budget_snapshot_json=budget_snapshot,
            policy_snapshot_json=policy_snapshot,
            target_snapshot_json=target_snapshot,
            content_hash=content_hash,
            effective_from=effective_from,
            created_by=created_by,
            updated_by=created_by,
        )
        plan.current_version_id = version.id
        plan.save(update_fields=["current_version_id", "updated_at"])
        return version

    @staticmethod
    def freeze_version(version: HrDevelopmentPlanVersion) -> bool:
        if version.status != PlanVersionStatus.DRAFT:
            return False
        version.status = PlanVersionStatus.FROZEN
        version.save(update_fields=["status", "updated_at"])
        return True
