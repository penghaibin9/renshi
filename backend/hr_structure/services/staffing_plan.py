"""
hr_structure/services/staffing_plan.py

StaffingPlanService —— 编制方案（总册 11 节）。

preflight 校验（11.9）：总分配超总量、负数、生效重叠、结构比例等 → BLOCKER/WARNING/INFO。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_structure.authority_registry import EVENT_STAFFING_PLAN_APPROVED

from hr_structure.models import (
    HrHeadcountQuotaLine,
    HrLeadershipQuotaLine,
    HrOrganization,
    HrPositionQuotaLine,
    HrPostCatalog,
    HrStaffingPlan,
)
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
        if plan.tenant_id != self.scope.tenant_id:
            result.issues.append(
                ValidationIssue("BLOCKER", "PLAN_CROSS_TENANT", "编制方案不属于当前学校")
            )
            return result
        if not lines and not plan.position_lines.exists() and not plan.leadership_lines.exists():
            result.issues.append(
                ValidationIssue("BLOCKER", "PLAN_HAS_NO_QUOTA_LINES", "编制方案至少需要一条额度明细")
            )
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

    def _draft_plan(self, plan_id) -> HrStaffingPlan:
        plan = HrStaffingPlan.objects.select_for_update().filter(
            tenant_id=self.scope.tenant_id, id=plan_id
        ).first()
        if plan is None:
            raise ValueError("编制方案不存在或跨租户")
        if plan.status != HrStaffingPlan.Status.DRAFT:
            raise ValueError("仅草稿编制方案可编辑额度明细")
        return plan

    def _organization(self, organization_id) -> HrOrganization:
        org = HrOrganization.objects.filter(
            tenant_id=self.scope.tenant_id,
            id=organization_id,
            identity_status=HrOrganization.IdentityStatus.ACTIVE,
        ).first()
        if org is None:
            raise ValueError("组织不存在、已停用或跨租户")
        return org

    @staticmethod
    def _non_negative_int(value, label):
        try:
            decimal_value = Decimal(str(value))
            if decimal_value < 0 or decimal_value != decimal_value.to_integral_value():
                raise InvalidOperation
            return int(decimal_value)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{label} 必须是非负整数")

    @staticmethod
    def _non_negative_decimal(value, label):
        try:
            parsed = Decimal(str(value))
            if parsed < 0:
                raise InvalidOperation
            return parsed
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{label} 必须是非负数")

    @transaction.atomic
    def add_headcount_line(
        self,
        *,
        plan_id,
        organization_id,
        staffing_basis,
        authorized_headcount,
        reserve_headcount=0,
        worker_category="",
        control_mode="HARD",
        notes="",
    ) -> HrHeadcountQuotaLine:
        plan = self._draft_plan(plan_id)
        org = self._organization(organization_id)
        if staffing_basis not in {
            value for value, _ in HrHeadcountQuotaLine.StaffingBasis.choices
        }:
            raise ValueError("用人编制口径非法")
        if control_mode not in {
            value for value, _ in HrHeadcountQuotaLine.ControlMode.choices
        }:
            raise ValueError("编制控制模式非法")
        return HrHeadcountQuotaLine.objects.create(
            plan_id=plan,
            tenant_id=self.scope.tenant_id,
            organization_id=org,
            staffing_basis=staffing_basis,
            worker_category=str(worker_category or "").strip(),
            authorized_headcount=self._non_negative_int(
                authorized_headcount, "核定人数"
            ),
            reserve_headcount=self._non_negative_int(
                reserve_headcount, "预留人数"
            ),
            control_mode=control_mode,
            notes=str(notes or "").strip(),
        )

    @transaction.atomic
    def add_position_line(
        self,
        *,
        plan_id,
        organization_id,
        post_category,
        authorized_positions,
        authorized_fte,
        post_grade="",
        post_catalog_id=None,
        control_mode="HARD",
    ) -> HrPositionQuotaLine:
        plan = self._draft_plan(plan_id)
        org = self._organization(organization_id)
        if not str(post_category or "").strip():
            raise ValueError("岗位类别不能为空")
        catalog = None
        if post_catalog_id:
            catalog = HrPostCatalog.objects.filter(
                tenant_id=self.scope.tenant_id, id=post_catalog_id
            ).first()
            if catalog is None:
                raise ValueError("岗位目录不存在或跨租户")
        if control_mode not in {"HARD", "SOFT", "INFO_ONLY"}:
            raise ValueError("岗位额度控制模式非法")
        return HrPositionQuotaLine.objects.create(
            plan_id=plan,
            tenant_id=self.scope.tenant_id,
            organization_id=org,
            post_category=str(post_category).strip(),
            post_grade=str(post_grade or "").strip(),
            post_catalog_id=catalog,
            authorized_positions=self._non_negative_int(
                authorized_positions, "核定岗位数"
            ),
            authorized_fte=self._non_negative_decimal(
                authorized_fte, "核定 FTE"
            ),
            control_mode=control_mode,
        )

    @transaction.atomic
    def add_leadership_line(
        self,
        *,
        plan_id,
        organization_id,
        leadership_level,
        quota_count,
        control_mode="HARD",
    ) -> HrLeadershipQuotaLine:
        plan = self._draft_plan(plan_id)
        org = self._organization(organization_id)
        if not str(leadership_level or "").strip():
            raise ValueError("领导职数层级不能为空")
        if control_mode not in {"HARD", "SOFT", "INFO_ONLY"}:
            raise ValueError("领导职数控制模式非法")
        return HrLeadershipQuotaLine.objects.create(
            plan_id=plan,
            tenant_id=self.scope.tenant_id,
            organization_id=org,
            leadership_level=str(leadership_level).strip(),
            quota_count=self._non_negative_int(quota_count, "核定职数"),
            control_mode=control_mode,
        )

    @transaction.atomic
    def create_plan(self, *, code, name, plan_year, validity_from, basis_document_no="") -> HrStaffingPlan:
        code = str(code or "").strip()
        name = str(name or "").strip()
        basis_document_no = str(basis_document_no or "").strip()
        if not code or not name:
            raise ValueError("编制方案编码和名称不能为空")
        try:
            plan_year = int(plan_year)
        except (TypeError, ValueError):
            raise ValueError("编制方案年度格式非法")
        if plan_year < 2000 or plan_year > 2100:
            raise ValueError("编制方案年度应在 2000 至 2100 之间")
        if validity_from.year != plan_year:
            raise ValueError("生效日期必须属于方案年度")
        if HrStaffingPlan.objects.filter(
            tenant_id=self.scope.tenant_id, code=code
        ).exists():
            raise ValueError("编制方案编码已存在")
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
    def submit(self, plan) -> HrStaffingPlan:
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
        return plan

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
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_STAFFING_PLAN_APPROVED,
            payload={
                "staffingPlanId": str(plan.id),
                "code": plan.code,
                "planYear": plan.plan_year,
                "version": plan.version_no,
                "effectiveDate": plan.validity_from.isoformat(),
            },
        )
        return plan

    @transaction.atomic
    def activate(self, plan) -> HrStaffingPlan:
        """已批准方案转为当前正式方案，旧方案按新生效日封口。"""
        plan = HrStaffingPlan.objects.select_for_update().filter(
            tenant_id=self.scope.tenant_id, id=plan.id
        ).first()
        if plan is None:
            raise ValueError("方案不存在")
        if plan.status == HrStaffingPlan.Status.EFFECTIVE:
            return plan
        if plan.status != HrStaffingPlan.Status.APPROVED:
            raise ValueError(f"当前状态 {plan.status} 不允许生效")
        if plan.validity_from > timezone.localdate():
            raise ValueError("尚未到方案生效日")

        overlapping = (
            HrStaffingPlan.objects.select_for_update()
            .filter(
                tenant_id=self.scope.tenant_id,
                status=HrStaffingPlan.Status.EFFECTIVE,
                validity_from__lt=plan.validity_to or date.max,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=plan.validity_from))
            .exclude(id=plan.id)
        )
        for previous in overlapping:
            if previous.validity_from >= plan.validity_from:
                raise ValueError("已存在同日或未来生效的编制方案")
            previous.validity_to = plan.validity_from
            previous.status = HrStaffingPlan.Status.SUPERSEDED
            previous.save(update_fields=["validity_to", "status"])
        plan.status = HrStaffingPlan.Status.EFFECTIVE
        plan.locked_at = timezone.now()
        plan.version_no += 1
        plan.save(update_fields=["status", "locked_at", "version_no"])
        return plan
