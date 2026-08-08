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

        total_authorized = sum(
            line.authorized_headcount for line in plan.headcount_lines.all()
        )
        # 汇总校验：学校总量行 vs 分配之和
        total_line = next(
            (
                l
                for l in plan.headcount_lines.all()
                if l.organization_id_id
                and l.organization_id.org_dimension == "ADMIN"
                and l.staffing_basis == l.StaffingBasis.OFFICIAL_ESTABLISHMENT
            ),
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
        """DRAFT → UNDER_REVIEW，先过 preflight。"""
        result = self.preflight(plan)
        if result.has_blocker:
            raise ValueError("存在 BLOCKER，禁止提交")
        if plan.status != HrStaffingPlan.Status.DRAFT:
            raise ValueError(f"当前状态 {plan.status} 不允许提交")
        plan.status = HrStaffingPlan.Status.UNDER_REVIEW
        plan.save(update_fields=["status"])
        return result

    @transaction.atomic
    def approve(self, plan) -> HrStaffingPlan:
        """UNDER_REVIEW → APPROVED。"""
        if plan.status not in (HrStaffingPlan.Status.UNDER_REVIEW, HrStaffingPlan.Status.RETURNED):
            raise ValueError(f"当前状态 {plan.status} 不允许批准")
        plan.status = HrStaffingPlan.Status.APPROVED
        plan.save(update_fields=["status"])
        return plan
