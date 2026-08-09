"""
hr_staff/services/employment_service.py —— 聘用关系写入（S3）。

- start_relationship：创建关系（同一 staff 允许多关系：返聘/外聘/再次入职，但同类型同区间不重叠）；
- end_relationship：结束关系（必须关闭/计划关闭未结束 assignment，不 DELETE）；
- 关系结束后不允许存在超出结束日期的 active assignment（不变量 #9）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Q

from hr_staff.constants import RelationshipStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment
from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.common import resolve_staff


class EmploymentService:
    def __init__(self, tenant_id: int, audit_actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.audit_actor_user_id = audit_actor_user_id

    @transaction.atomic
    def start_relationship(
        self,
        *,
        staff_id,
        relationship_type: str,
        employment_type: str = "",
        effective_from: date,
        effective_to: Optional[date] = None,
        source_business_type: str = "",
        source_business_id: str = "",
        reason_code: str = "",
    ) -> HrEmploymentRelationship:
        # P1-6：staff 必须属于当前 tenant（UUID/实例归一）
        staff = resolve_staff(self.tenant_id, staff_id)
        if effective_to is not None and effective_to <= effective_from:
            raise AssignmentPolicyViolation(
                "EFFECTIVE_DATE_INVALID", "effective_to 必须晚于 effective_from"
            )
        # 同 staff 同类型同区间不得重叠（返聘属 REHIRE/RETIRED_REHIRE 不同类型，允许共存）
        overlap = HrEmploymentRelationship.objects.filter(
            tenant_id=self.tenant_id,
            staff_id=staff,
            relationship_type=relationship_type,
            status=RelationshipStatus.ACTIVE,
        ).filter(
            effective_from__lt=(effective_to or date.max),
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from)
        )
        if overlap.exists():
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OVERLAP", "同类型聘用关系区间重叠"
            )

        rel = HrEmploymentRelationship.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            relationship_type=relationship_type,
            employment_type=employment_type,
            effective_from=effective_from,
            effective_to=effective_to,
            source_business_type=source_business_type,
            source_business_id=source_business_id,
            reason_code=reason_code,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="EmploymentRelationshipStarted",
            actor_user_id=self.audit_actor_user_id,
            staff_id=staff.id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=reason_code,
        )
        return rel

    @transaction.atomic
    def end_relationship(
        self,
        *,
        relationship_id,
        effective_to: date,
        reason_code: str = "",
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrEmploymentRelationship:
        rel = (
            HrEmploymentRelationship.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=relationship_id)
            .first()
        )
        if rel is None:
            raise AssignmentPolicyViolation("RELATIONSHIP_NOT_FOUND", "聘用关系不存在")
        if effective_to <= rel.effective_from:
            raise AssignmentPolicyViolation(
                "EFFECTIVE_DATE_INVALID", "结束日期必须晚于生效日期"
            )
        # 未结束的 assignment 必须关闭或计划关闭（不变量 #9）
        open_assignments = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id=rel,
            status="ACTIVE",
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_to))
        if open_assignments.exists():
            for assignment in open_assignments:
                assignment.effective_to = effective_to
                assignment.status = "ENDED"
                assignment.version += 1
                assignment.save(
                    update_fields=["effective_to", "status", "version", "updated_at"]
                )
        rel.effective_to = effective_to
        rel.status = RelationshipStatus.ENDED
        rel.reason_code = reason_code or rel.reason_code
        rel.version += 1
        rel.save(update_fields=["effective_to", "status", "reason_code", "version", "updated_at"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="EmploymentRelationshipEnded",
            actor_user_id=self.audit_actor_user_id,
            staff_id=rel.staff_id_id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=reason_code,
        )
        self._refresh_staff_projection(rel.staff_id_id)  # P1-9：投影不陈旧
        return rel

    def _refresh_staff_projection(self, staff_id):
        """结束关系后刷新 StaffMaster 当前状态投影（可由权威事实重建）。"""
        from hr_staff.models import HrStaffMaster
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        staff = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff_id).first()
        if staff is None:
            return
        qs = EffectiveDatedQueryService(self.tenant_id)
        staff.current_employment_status = qs.status_as_of(staff.id)
        primary = qs.primary_assignment_as_of(staff.id)
        staff.primary_assignment_id = primary.id if primary else None
        staff.version += 1
        staff.save(
            update_fields=["current_employment_status", "primary_assignment_id", "version", "updated_at"]
        )
