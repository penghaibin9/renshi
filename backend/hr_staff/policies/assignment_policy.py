"""
hr_staff/policies/assignment_policy.py —— 任职不变量校验（S3）。

校验项：
- PRIMARY 唯一（同关系同日期最多一个；开放 PRIMARY 已由 DB 条件唯一兜底，重叠段由服务校验）；
- FTE 上限（学校策略可配，V1 默认单关系任一时点合计 ≤ 1.5，角色型 CONCURRENT FTE=0 允许）；
- 跨 tenant 引用拒绝（organization/position/post catalog/reporting staff 必须同 tenant）；
- organization/position/post catalog 在 as_of 有效，且 position 必须属于所选 organization；
- assignment 必须完整落在 employment relationship 生效区间内；
- POSITION_CONTROL 岗位不超占（按 as-of 岗位版本计算）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Q

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

    def validate_cross_tenant_ref(
        self,
        *,
        organization_id=None,
        position_id=None,
        post_catalog_id=None,
        reporting_staff_id=None,
    ):
        checks = (
            (organization_id, "组织"),
            (position_id, "岗位"),
            (post_catalog_id, "岗位目录"),
            (reporting_staff_id, "汇报对象"),
        )
        for obj, label in checks:
            if obj is not None and getattr(obj, "tenant_id", None) != self.tenant_id:
                raise AssignmentPolicyViolation(
                    "CROSS_TENANT_REFERENCE", f"{label}不属于当前学校"
                )

    def validate_relationship_window(
        self,
        *,
        relationship,
        effective_from: date,
        effective_to: Optional[date],
    ):
        """任职事实必须完整落在所属聘用关系的有效区间内。"""
        if getattr(relationship, "tenant_id", None) != self.tenant_id:
            raise AssignmentPolicyViolation(
                "CROSS_TENANT_REFERENCE", "employment relationship 不属于当前学校"
            )
        if relationship.status in ("DRAFT", "CANCELLED"):
            raise AssignmentPolicyViolation(
                "RELATIONSHIP_NOT_ASSIGNABLE", "聘用关系尚未生效或已取消，不能创建任职"
            )
        if effective_from < relationship.effective_from:
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OUTSIDE_RELATIONSHIP",
                "任职开始日期不能早于聘用关系开始日期",
            )
        if relationship.effective_to and effective_from >= relationship.effective_to:
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OUTSIDE_RELATIONSHIP",
                "任职开始日期已超出聘用关系有效期",
            )
        if (
            effective_to is not None
            and relationship.effective_to is not None
            and effective_to > relationship.effective_to
        ):
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OUTSIDE_RELATIONSHIP",
                "任职结束日期不能晚于聘用关系结束日期",
            )

    def validate_org_position_as_of(
        self,
        *,
        organization_id,
        position_id,
        as_of: date,
        post_catalog_id=None,
    ):
        """HR02 权威引用在 as_of 必须有效且彼此一致。"""
        if organization_id is not None:
            from hr_structure.selectors.effective import org_version_as_of

            version = org_version_as_of(self.tenant_id, organization_id.id, as_of)
            if version is None:
                raise AssignmentPolicyViolation(
                    "EFFECTIVE_DATE_INVALID",
                    f"组织 {organization_id.stable_code} 在 {as_of} 无有效版本",
                )
            if organization_id.identity_status == "CLOSED":
                closed_at = getattr(organization_id, "closed_at", None)
                # CLOSED 但没有可证明的关闭日时 fail-closed；有关闭日则允许关闭前的历史更正。
                if closed_at is None or as_of >= closed_at.date():
                    raise AssignmentPolicyViolation(
                        "ORGANIZATION_NOT_ASSIGNABLE",
                        f"组织 {organization_id.stable_code} 在 {as_of} 已关闭",
                    )

        if position_id is not None:
            from hr_structure.selectors.effective import position_as_of

            position_snapshot = position_as_of(self.tenant_id, position_id.id, as_of)
            if position_snapshot is None:
                raise AssignmentPolicyViolation(
                    "EFFECTIVE_DATE_INVALID",
                    f"岗位 {position_id.position_code} 在 {as_of} 无有效版本",
                )
            lifecycle_status = getattr(position_snapshot, "lifecycle_status", "")
            if lifecycle_status != "ACTIVE":
                raise AssignmentPolicyViolation(
                    "POSITION_NOT_ASSIGNABLE",
                    f"岗位 {position_id.position_code} 在 {as_of} 状态为 {lifecycle_status or 'UNKNOWN'}，不能新增任职",
                )
            snapshot_org_id = getattr(position_snapshot, "organization_id_id", None)
            if organization_id is None:
                raise AssignmentPolicyViolation(
                    "POSITION_ORG_REQUIRED", "选择 HR02 岗位时必须同时绑定其所属 HR02 组织"
                )
            if snapshot_org_id != organization_id.id:
                raise AssignmentPolicyViolation(
                    "POSITION_ORG_MISMATCH", "所选岗位在生效日不属于所选组织"
                )
            if post_catalog_id is not None:
                snapshot_catalog_id = getattr(position_snapshot, "post_catalog_version_id_id", None)
                if snapshot_catalog_id != post_catalog_id.id:
                    raise AssignmentPolicyViolation(
                        "POSITION_CATALOG_MISMATCH", "所选岗位与岗位目录版本不一致"
                    )

        if post_catalog_id is not None:
            if post_catalog_id.status != "ACTIVE":
                raise AssignmentPolicyViolation(
                    "POST_CATALOG_NOT_ASSIGNABLE", "岗位目录版本未启用，不能新增任职"
                )
            if post_catalog_id.validity_from > as_of or (
                post_catalog_id.validity_to and post_catalog_id.validity_to <= as_of
            ):
                raise AssignmentPolicyViolation(
                    "POST_CATALOG_NOT_ASSIGNABLE", "岗位目录版本在任职生效日无效"
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

    def validate_total_fte(
        self,
        *,
        relationship_id,
        fte: Decimal,
        effective_from: date,
        effective_to: Optional[date],
        exclude_assignment_id=None,
    ):
        """同一聘用关系任一时点的有效任职 FTE 合计不得超过策略上限。"""
        new_fte = Decimal(str(fte))
        qs = (
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=relationship_id,
            )
            .exclude(status__in=("DRAFT", "CANCELLED"))
            .filter(effective_from__lt=(effective_to or date.max))
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from))
        )
        if exclude_assignment_id:
            qs = qs.exclude(id=exclude_assignment_id)
        segments = list(qs.values("effective_from", "effective_to", "fte"))
        points = {effective_from}
        for segment in segments:
            start = segment["effective_from"]
            if start >= effective_from and (effective_to is None or start < effective_to):
                points.add(start)
        for point in points:
            total = new_fte
            for segment in segments:
                if segment["effective_from"] <= point and (
                    segment["effective_to"] is None or segment["effective_to"] > point
                ):
                    total += Decimal(str(segment["fte"]))
            if total > self.max_total_fte:
                raise AssignmentPolicyViolation(
                    "FTE_POLICY_EXCEEDED",
                    f"{point} 时点任职 FTE 合计 {total} 超过策略上限 {self.max_total_fte}",
                )

    def validate_position_capacity(
        self, *, position_id, effective_from: date, exclude_assignment_id=None
    ):
        """POSITION_CONTROL 岗位不超占；以 effective_from 的岗位版本为准。"""
        if position_id is None:
            return
        from hr_structure.selectors.effective import position_as_of

        snapshot = position_as_of(self.tenant_id, position_id.id, effective_from)
        if snapshot is None or getattr(snapshot, "lifecycle_status", "") != "ACTIVE":
            return  # 可任职性由 validate_org_position_as_of 给出精确错误
        max_incumbents = getattr(snapshot, "max_incumbents", position_id.max_incumbents)
        allow_multiple = getattr(
            snapshot, "allow_multiple_incumbents", position_id.allow_multiple_incumbents
        )
        if max_incumbents <= 0 or allow_multiple:
            return

        qs = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            position_id=position_id,
            status="ACTIVE",
        ).filter(
            effective_from__lte=effective_from,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from))
        if exclude_assignment_id:
            qs = qs.exclude(id=exclude_assignment_id)
        if qs.count() >= max_incumbents:
            raise AssignmentPolicyViolation(
                "POSITION_CAPACITY_EXCEEDED",
                f"岗位 {position_id.position_code} 已占满",
            )
