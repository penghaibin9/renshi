"""
hr_staff/services/effective_dated_query_service.py —— 统一 as-of 查询服务（总册 §9.1）。

硬合同：
- 统一半开区间 [effective_from, effective_to)，NULL=开放结束；
- 全部 as-of 查询必须走本服务，禁止各页面自行拼日期条件；
- 历史 as-of 禁止读取 current projection 替代（不变量 #12）；
- 组织名称历史解析委托 hr_structure.selectors.effective.org_version_as_of（HR02 门）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Count, Q
from django.utils import timezone

from hr_staff.constants import AssignmentType, StaffStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment, HrStatusHistory


def _active_segments(qs, as_of: date, *, exclude_status=("DRAFT", "CANCELLED")):
    """
    日期区间过滤（[effective_from, effective_to) 半开）：
    - 只排除语义上从未生效的 DRAFT/CANCELLED（对无 status 字段的模型传 exclude_status=()）；
    - ENDED 段在其有效区间内仍是合法历史（P0-1 修复：历史 as-of 必须能还原关闭段）。
    """
    qs = qs.filter(
        effective_from__lte=as_of,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
    if exclude_status:
        qs = qs.exclude(status__in=exclude_status)
    return qs


class EffectiveDatedQueryService:
    """HR03 唯一 as-of 查询入口（只读）。"""

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    # ---- 关系 ----

    def relationships_as_of(self, staff_id, as_of: Optional[date] = None):
        as_of = as_of or timezone.localdate()
        return _active_segments(
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ),
            as_of,
        ).order_by("effective_from")

    # ---- 任职 ----

    def assignments_as_of(self, staff_id, as_of: Optional[date] = None):
        as_of = as_of or timezone.localdate()
        return (
            _active_segments(
                HrStaffAssignment.objects.filter(
                    tenant_id=self.tenant_id,
                    employment_relationship_id__staff_id=staff_id,
                ),
                as_of,
            )
            .select_related("organization_id", "position_id", "post_catalog_id")
            .order_by("effective_from")
        )

    def assignments_for_relationship_as_of(self, relationship_id, as_of: Optional[date] = None):
        as_of = as_of or timezone.localdate()
        return _active_segments(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=relationship_id,
            ),
            as_of,
        ).order_by("effective_from")

    def primary_assignment_as_of(self, staff_id, as_of: Optional[date] = None):
        as_of = as_of or timezone.localdate()
        return (
            self.assignments_as_of(staff_id, as_of)
            .filter(assignment_type=AssignmentType.PRIMARY)
            .first()
        )

    # ---- 按组织/岗位反查（HR02 OccupancyProvider 消费入口，P1-b）----

    def assignments_for_org_as_of(self, organization_id, as_of: Optional[date] = None):
        """某组织在 as_of 的全部任职段（半开区间 + ENDED 合法历史语义）。"""
        as_of = as_of or timezone.localdate()
        return _active_segments(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                organization_id=organization_id,
            ),
            as_of,
        ).select_related("employment_relationship_id__staff_id")

    def assignments_for_position_as_of(self, position_id, as_of: Optional[date] = None):
        """某岗位在 as_of 的全部任职段（用于 POSITION_CONTROL 占用计算）。"""
        as_of = as_of or timezone.localdate()
        return _active_segments(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                position_id=position_id,
            ),
            as_of,
        ).select_related("employment_relationship_id__staff_id")

    def position_occupancy_as_of(self, position_id, as_of: Optional[date] = None) -> int:
        """岗位在 as_of 的有效任职人数（HR02 occupancy 用）。"""
        return self.assignments_for_position_as_of(position_id, as_of).count()

    def position_occupancy_by_position_as_of(
        self, position_ids, as_of: Optional[date] = None
    ) -> dict:
        """批量返回岗位有效任职数，供 HR02 列表/汇总避免逐岗查询。"""
        as_of = as_of or timezone.localdate()
        position_ids = tuple(position_ids)
        if not position_ids:
            return {}
        rows = (
            _active_segments(
                HrStaffAssignment.objects.filter(
                    tenant_id=self.tenant_id,
                    position_id__in=position_ids,
                ),
                as_of,
            )
            .values("position_id")
            .annotate(occupied_count=Count("id"))
        )
        return {
            row["position_id"]: row["occupied_count"]
            for row in rows
        }

    def org_occupancy_as_of(self, organization_id, as_of: Optional[date] = None) -> int:
        """组织在 as_of 的有效任职人数。"""
        return self.assignments_for_org_as_of(organization_id, as_of).count()

    # ---- 状态推导（投影）----

    def status_as_of(self, staff_id, as_of: Optional[date] = None) -> str:
        """
        由关系/任职段推导 Staff 状态投影（按 as_of 历史区间解释）：
        - 显式 HrStatusHistory 命中 → 用之；
        - 有"区间覆盖 as_of 的关系段"（含 ENDED 历史段）→ ACTIVE；
        - 仅有未来关系 → PENDING_ENTRY；
        - 全部已结束 → 按最近结束原因区分 RETIRED/DEPARTED；
        - 无任何关系 → PENDING_ENTRY。
        """
        as_of = as_of or timezone.localdate()
        explicit = _active_segments(
            HrStatusHistory.objects.filter(tenant_id=self.tenant_id, staff_id=staff_id),
            as_of,
            exclude_status=(),
        ).order_by("-effective_from").first()
        if explicit:
            return explicit.status_code

        rel = _active_segments(
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ),
            as_of,
        ).exists()
        if rel:
            return StaffStatus.ACTIVE

        # P2：future/last_ended 分支排除 DRAFT/CANCELLED（未生效/取消段不参与状态推导）
        future = HrEmploymentRelationship.objects.filter(
            tenant_id=self.tenant_id,
            staff_id=staff_id,
            effective_from__gt=as_of,
        ).exclude(status__in=("DRAFT", "CANCELLED")).exists()
        if future:
            return StaffStatus.PENDING_ENTRY

        last_ended = (
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id,
                staff_id=staff_id,
                effective_to__isnull=False,
            )
            .exclude(status__in=("DRAFT", "CANCELLED"))
            .order_by("-effective_to")
            .first()
        )
        if last_ended and (
            "RETIRE" in (last_ended.reason_code or "").upper()
            or last_ended.relationship_type in ("RETIRED_REHIRE",)
        ):
            return StaffStatus.RETIRED
        return StaffStatus.DEPARTED

    # ---- Timeline（任职履历聚合）----

    def timeline(self, staff_id):
        """按时间排序的任职/关系事件（关系段 + 任职段 + 状态段）。"""
        events = []
        for rel in HrEmploymentRelationship.objects.filter(
            tenant_id=self.tenant_id, staff_id=staff_id
        ).order_by("effective_from"):
            events.append(
                {
                    "kind": "relationship",
                    "id": str(rel.id),
                    "effective_from": rel.effective_from,
                    "effective_to": rel.effective_to,
                    "label": rel.get_relationship_type_display(),
                    "status": rel.status,
                }
            )
        for ass in HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id, employment_relationship_id__staff_id=staff_id
        ).select_related("organization_id"):
            events.append(
                {
                    "kind": "assignment",
                    "id": str(ass.id),
                    "effective_from": ass.effective_from,
                    "effective_to": ass.effective_to,
                    "label": f"{ass.get_assignment_type_display()} {ass.organization_id.stable_code if ass.organization_id else ''}",
                    "status": ass.status,
                }
            )
        events.sort(key=lambda e: (e["effective_from"] or date.min, e["kind"]))
        return events

    # ---- HR02 组织名称 as-of 解析 ----

    def org_name_as_of(self, organization_id, as_of: date) -> Optional[str]:
        """组织在 as_of 的名称（委托 HR02 org_version_as_of，带 tenant 防泄漏）。"""
        if not organization_id:
            return None
        from hr_structure.selectors.effective import org_version_as_of

        version = org_version_as_of(self.tenant_id, organization_id, as_of)
        return version.name if version else None
