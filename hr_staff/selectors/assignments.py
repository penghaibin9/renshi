"""
hr_staff/selectors/assignments.py —— HR03-03 任职与身份履历（S6，只读）。

硬合同（总册 §12）：
- timeline + 表格双视图数据；历史 as-of 必须走 EffectiveDatedQueryService；
- 历史日期页面绝不显示当前学院（#55 负向）；
- 新建任职事实来源白名单（HR05/06/14/16/MIGRATION_VERIFIED/AUTHORIZED_CORRECTION）由 S10 事件接收落实；
  本 selector 只读。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from hr_staff.context import HrStaffRequestContext
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment
from hr_staff.policies.scope_policy import StaffNotFound
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class AssignmentHistorySelector:
    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id
        self.as_of = context.as_of or date.today()
        self.qs = EffectiveDatedQueryService(self.tenant_id)

    def _deny_check(self, staff_id):
        """P1-5：读路径强制 data scope（tenant + scope + fail-closed）。"""
        from hr_staff.policies.scope_policy import ScopeEnforcer

        return ScopeEnforcer(self.context).get_staff_or_deny(staff_id)

    def relationships(self, staff_id) -> list[dict]:
        """全部关系段（含历史，按 effective_from 排序）。"""
        self._deny_check(staff_id)  # P1-5
        rels = HrEmploymentRelationship.objects.filter(
            tenant_id=self.tenant_id, staff_id=staff_id
        ).order_by("effective_from")
        return [
            {
                "id": str(r.id),
                "relationshipType": r.relationship_type,
                "employmentType": r.employment_type,
                "effectiveFrom": r.effective_from.isoformat(),
                "effectiveTo": r.effective_to.isoformat() if r.effective_to else None,
                "status": r.status,
                "sourceBusinessType": r.source_business_type,
                "sourceBusinessId": r.source_business_id,
            }
            for r in rels
        ]

    def assignments(self, staff_id, as_of: Optional[date] = None) -> dict:
        """as-of 任职段（默认今天）；同时返回当前有效与历史已结束段。"""
        self._deny_check(staff_id)  # P1-5
        as_of = as_of or self.as_of
        active = list(self.qs.assignments_as_of(staff_id, as_of))
        historical = list(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id__staff_id=staff_id,
            )
            .exclude(id__in=[a.id for a in active])
            .select_related("organization_id", "position_id")
            .order_by("-effective_from")
        )
        return {
            "asOf": as_of.isoformat(),
            "active": [self._row(a, as_of) for a in active],
            "historical": [self._row(a, as_of) for a in historical],
        }

    def timeline(self, staff_id) -> list[dict]:
        """时间线事件（关系段+任职段+状态段）。"""
        self._deny_check(staff_id)  # P1-5
        return self.qs.timeline(staff_id)

    def _row(self, assignment: HrStaffAssignment, as_of: date) -> dict:
        org_name = None
        if assignment.organization_id:
            org_name = self.qs.org_name_as_of(assignment.organization_id_id, as_of) or (
                assignment.organization_id.stable_code
            )
        elif assignment.legacy_department_id:
            org_name = f"legacy:{assignment.legacy_department_id}"
        return {
            "id": str(assignment.id),
            "relationshipId": str(assignment.employment_relationship_id_id),
            "assignmentType": assignment.assignment_type,
            "orgId": (
                str(assignment.organization_id_id) if assignment.organization_id else None
            ),
            "orgName": org_name,
            "positionName": (
                assignment.position_id.position_code if assignment.position_id else None
            ),
            "roleCode": assignment.assignment_role_code,
            "fte": str(assignment.fte),
            "effectiveFrom": assignment.effective_from.isoformat(),
            "effectiveTo": assignment.effective_to.isoformat() if assignment.effective_to else None,
            "status": assignment.status,
            "sourceBusinessType": assignment.source_business_type,
            "sourceBusinessId": assignment.source_business_id,
        }
