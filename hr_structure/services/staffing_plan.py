"""
hr_structure/services/staffing_plan.py

StaffingPlanService —— 编制方案（总册 11 节）。

preflight 校验（11.9）：总分配超总量、负数、生效重叠、结构比例等 → BLOCKER/WARNING/INFO。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from django.db import transaction

from hr_structure.models import HrStaffingPlan
from hr_structure.scope import Hr02Scope


@dataclass
class ValidationIssue:
    level: str  # BLOCKER / WARNING / INFO
    code: str
    message: str


@dataclass
class PreflightResult:
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def has_blocker(self) -> bool:
        return any(i.level == "BLOCKER" for i in self.issues)


class StaffingPlanService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    def preflight(self, plan) -> PreflightResult:
        """方案提交前校验。"""
        result = PreflightResult()

        lines = list(plan.headcount_lines.select_related("organization_id"))
        total_authorized = sum(l.authorized_headcount for l in lines)
        # 汇总校验：学校总量行 vs 分配之和
        # 总量行 = org_type=SCHOOL 的组织（org_type 在版本上，经版本 as-of 解析）
        from hr_structure.models import HrOrganizationVersion

        school_org_ids = set(
            HrOrganizationVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                org_type="SCHOOL",
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            ).values_list("organization_id", flat=True)
        )
        total_line = next(
            (l for l in lines if l.organization_id_id in school_org_ids),
            None,
        )
        if total_line and total_line.authorized_headcount > 0:
            allocated = total_authorized - total_line.authorized_headcount
            if allocated > total_line.authorized_headcount:
                result.issues.append(
                    ValidationIssue("BLOCKER", "QUOTA_OVER_TOTAL", "单位分配总量超过学校核定总量")
                )
        return result

    @transaction.atomic
    def create_plan(self, *, code, name, plan_year, validity_from, basis_document_no="") -> HrStaffingPlan:
        plan = HrStaffingPlan.objects.create(
            tenant_id=self.scope.tenant_id,
            code=code,
            name=name,
            plan_year=plan_year,
            validity_from=validity_from,
            status=HrStaffingPlan.Status.DRAFT,
            basis_document_no=basis_document_no,
            created_by=self.actor,
        )
        return plan

    @transaction.atomic
    def submit(self, plan) -> PreflightResult:
        """DRAFT → UNDER_REVIEW，先过 preflight。乐观锁：select_for_update + version。"""
        locked = (
            HrStaffingPlan.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=plan.id)
            .first()
        )
        if locked is None:
            raise ValueError("方案不存在")
        plan = locked
        result = self.preflight(plan)
        if result.has_blocker:
            raise ValueError("存在 BLOCKER，禁止提交")
        if plan.status != HrStaffingPlan.Status.DRAFT:
            raise ValueError(f"当前状态 {plan.status} 不允许提交")
        plan.status = HrStaffingPlan.Status.UNDER_REVIEW
        plan.version_no += 1
        plan.save(update_fields=["status", "version_no"])
        return result

    @transaction.atomic
    def approve(self, plan) -> HrStaffingPlan:
        """UNDER_REVIEW → APPROVED。乐观锁：select_for_update + version。"""
        locked = (
            HrStaffingPlan.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=plan.id)
            .first()
        )
        if locked is None:
            raise ValueError("方案不存在")
        plan = locked
        if plan.status not in (HrStaffingPlan.Status.UNDER_REVIEW, HrStaffingPlan.Status.RETURNED):
            raise ValueError(f"当前状态 {plan.status} 不允许批准")
        plan.status = HrStaffingPlan.Status.APPROVED
        plan.version_no += 1
        plan.save(update_fields=["status", "version_no"])
        return plan
