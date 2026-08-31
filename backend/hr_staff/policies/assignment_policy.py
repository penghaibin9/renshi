"""
hr_staff/policies/assignment_policy.py —— 任职不变量校验（S3）。

校验项：
- PRIMARY 唯一（同关系同日期最多一个；开放 PRIMARY 已由 DB 条件唯一兜底，重叠段由服务校验）；
- FTE 上限（学校策略可配，V1 默认单关系合计 ≤ 1.5，角色型 CONCURRENT FTE=0 允许）；
- 跨 tenant 引用拒绝（organization/position 必须同 tenant）；
- organization/position as_of 有效（委托 HR02 EffectiveDatedQueryService）；
- POSITION_CONTROL 岗位不超占（V1 轻量：incumbent 数量 < max_incumbents）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from hr_staff.constants import AssignmentType
from hr_staff.models import HrStaffAssignment


class AssignmentPolicyViolation(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class AssignmentPolicy:
    """纯校验（无副作用）；抛 AssignmentPolicyViolation 阻断。"""

    def __init__(self, tenant_id: int, max_total_fte: Decimal = Decimal("1.50")):
        self.tenant_id = tenant_id
        self.max_total_fte = max_total_fte

    def validate_fte(self, fte: Decimal):
        if fte is None or fte < 0:
            raise AssignmentPolicyViolation("INVALID_FTE", "FTE 不能为负")
        if fte > self.max_total_fte:
            raise AssignmentPolicyViolation(
                "FTE_POLICY_EXCEEDED", f"FTE 超过策略上限 {self.max_total_fte}"
            )

    def validate_cross_tenant_ref(self, *, organization_id=None, position_id=None):
        if organization_id is not None and organization_id.tenant_id != self.tenant_id:
            raise AssignmentPolicyViolation("CROSS_TENANT_REFERENCE", "组织不属于当前学校")
        if position_id is not None and position_id.tenant_id != self.tenant_id:
            raise AssignmentPolicyViolation("CROSS_TENANT_REFERENCE", "岗位不属于当前学校")

    def validate_org_position_as_of(self, *, organization_id, position_id, as_of: date):
        """organization/position 在 as_of 必须有效（HR02 门）。"""
        if organization_id is not None:
            from hr_structure.selectors.effective import org_version_as_of

            version = org_version_as_of(self.tenant_id, organization_id.id, as_of)
            if version is None:
                raise AssignmentPolicyViolation(
                    "EFFECTIVE_DATE_INVALID",
                    f"组织 {organization_id.stable_code} 在 {as_of} 无有效版本",
                )
        if position_id is not None:
            if position_id.validity_from > as_of:
                raise AssignmentPolicyViolation(
                    "EFFECTIVE_DATE_INVALID",
                    f"岗位 {position_id.position_code} 在 {as_of} 未生效",
                )
            if position_id.validity_to and position_id.validity_to <= as_of:
                raise AssignmentPolicyViolation(
                    "EFFECTIVE_DATE_INVALID",
                    f"岗位 {position_id.position_code} 在 {as_of} 已失效",
                )

    def validate_primary_overlap(
        self,
        *,
        relationship_id,
        effective_from: date,
        effective_to: Optional[date],
        exclude_assignment_id=None,
    ):
        """同关系 PRIMARY 段不得与既有 PRIMARY 段重叠（含新开放段）。"""
        qs = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id=relationship_id,
            assignment_type=AssignmentType.PRIMARY,
        )
        if exclude_assignment_id:
            qs = qs.exclude(id=exclude_assignment_id)
        from django.db.models import Q

        overlap = qs.filter(
            effective_from__lt=(effective_to or date.max),
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from)
        )
        if overlap.exists():
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OVERLAP",
                "同关系 PRIMARY 任职段存在重叠（历史区间不得无语义重叠）",
            )

    def validate_position_capacity(self, *, position_id, effective_from: date, exclude_assignment_id=None):
        """POSITION_CONTROL 岗位不超占（V1 轻量校验）。"""
        if position_id is None or position_id.lifecycle_status not in ("ACTIVE",):
            return
        if position_id.max_incumbents <= 0 or position_id.allow_multiple_incumbents:
            return
        from django.db.models import Q

        qs = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            position_id=position_id,
            status="ACTIVE",
        ).filter(
            effective_from__lte=effective_from,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from))
        if exclude_assignment_id:
            qs = qs.exclude(id=exclude_assignment_id)
        if qs.count() >= position_id.max_incumbents:
            raise AssignmentPolicyViolation(
                "POSITION_CAPACITY_EXCEEDED",
                f"岗位 {position_id.position_code} 已占满",
            )
