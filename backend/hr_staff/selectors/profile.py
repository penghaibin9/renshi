"""
hr_staff/selectors/profile.py —— HR03-02 主档 Profile bootstrap（S5，只读）。

硬合同（总册 §11/§26）：
- GET /api/hr/v1/staff/{staffId}/profile?asOf=
- 只返回当前页面必要摘要，不塞所有材料正文/所有审计/所有历史；
- asOf 切历史 → 只读事实，编辑入口由前端禁用；
- 高敏字段不进 bootstrap；reveal 走独立 endpoint（S8 实现）；
- 组织名称按 asOf 解析（HR02 EffectiveDatedQueryService）；
- 查询预算：profile ≤ 15~25 SQL。
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone
from typing import Optional

from django.db.models import Q

from hr_staff.constants import AssignmentType, StaffStatus
from hr_staff.context import HrStaffRequestContext
from hr_staff.models import (
    HrEmploymentRelationship,
    HrPerson,
    HrPersonIdentityDocument,
    HrStaffAssignment,
    HrStaffMaster,
)
from hr_staff.policies.scope_policy import StaffNotFound, StaffScopeDenied
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class ProfileSelector:
    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id
        self.as_of = context.as_of or timezone.localdate()
        self.qs = EffectiveDatedQueryService(self.tenant_id)

    def get_staff_or_deny(self, staff_id) -> HrStaffMaster:
        staff = (
            HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff_id)
            .select_related("person_id")
            .first()
        )
        if staff is None:
            raise StaffNotFound()
        # scope 校验统一走 ScopeEnforcer（P1-5）
        from hr_staff.policies.scope_policy import ScopeEnforcer

        ScopeEnforcer(self.context).assert_accessible(staff)
        return staff

    def _assert_scope_allows(self, staff):
        """兼容旧调用（不再使用；scope 判定统一走 ScopeEnforcer）。"""
        from hr_staff.policies.scope_policy import ScopeEnforcer

        ScopeEnforcer(self.context).assert_accessible(staff)

    # ------------------------------------------------------------------
    # bootstrap
    # ------------------------------------------------------------------
    def bootstrap(self, staff_id) -> dict:
        staff = self.get_staff_or_deny(staff_id)

        person = staff.person_id
        # P1-e：关系列表统一走 as-of 语义（半开区间 + ENDED 历史段可还原），
        # 与主岗/任职段口径一致（修复前 status=ACTIVE 过滤把历史 ENDED 关系排除）。
        relationships = list(self.qs.relationships_as_of(staff.id, self.as_of))
        active_rels = relationships

        primary = self.qs.primary_assignment_as_of(staff.id, self.as_of)
        concurrent = [
            a
            for a in self.qs.assignments_as_of(staff.id, self.as_of)
            if a.assignment_type != AssignmentType.PRIMARY
        ]

        identity = (
            HrPersonIdentityDocument.objects.filter(
                tenant_id=self.tenant_id, person_id=person, document_number_fingerprint__isnull=False
            )
            .exclude(document_number_fingerprint="")
            .first()
        )

        return {
            "identityHeader": {
                "staffId": str(staff.id),
                "staffUid": str(staff.staff_uid),
                "staffNo": staff.staff_no,
                "legalName": person.legal_name,
                "preferredName": person.preferred_name,
                "staffCategoryCode": staff.staff_category_code,
                "employmentStatus": self.qs.status_as_of(staff.id, self.as_of),
                "dataBasis": self._data_basis(),
            },
            "currentFacts": {
                "primaryAssignment": self._assignment_summary(primary),
                "concurrentAssignments": [self._assignment_summary(a) for a in concurrent],
                "relationships": [
                    {
                        "id": str(r.id),
                        "relationshipType": r.relationship_type,
                        "employmentType": r.employment_type,
                        "effectiveFrom": r.effective_from.isoformat(),
                        "effectiveTo": r.effective_to.isoformat() if r.effective_to else None,
                    }
                    for r in active_rels
                ],
                # P2-7：dateJoining 只取"在 as_of 之前已生效"的关系段（不含未来段/as_of 后才开始）
                "dateJoining": min(
                    (r.effective_from for r in relationships if r.effective_from <= self.as_of),
                    default=None,
                ).isoformat()
                if relationships
                else None,
            },
            "identitySummary": {
                "maskedIdentityNo": identity.masked_display if identity else None,
                "gender": person.gender_code,
                "birthYear": person.birth_date.year if person.birth_date else None,
            },
            "asOf": self.as_of.isoformat(),
            # P2-7：历史视图判定用学校时区今天（context.today），而非服务器 date.today()
            "isHistoricalView": self.as_of != self.context.today(),
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _assignment_summary(self, assignment: Optional[HrStaffAssignment]) -> Optional[dict]:
        if assignment is None:
            return None
        org_name = None
        if assignment.organization_id:
            org_name = self.qs.org_name_as_of(assignment.organization_id_id, self.as_of) or (
                assignment.organization_id.stable_code
            )
        elif assignment.legacy_department_id:
            org_name = f"legacy:{assignment.legacy_department_id}"
        return {
            "id": str(assignment.id),
            "assignmentType": assignment.assignment_type,
            "orgId": str(assignment.organization_id_id) if assignment.organization_id else None,
            "orgName": org_name,
            "positionName": (
                assignment.position_id.position_code if assignment.position_id else None
            ),
            "roleCode": assignment.assignment_role_code,
            "fte": str(assignment.fte),
            "effectiveFrom": assignment.effective_from.isoformat(),
            "effectiveTo": assignment.effective_to.isoformat() if assignment.effective_to else None,
        }

    def _data_basis(self) -> str:
        if self.context.authority_mode == "HR03_AUTHORITY":
            return "HR03_AUTHORITY"
        return "LEGACY_CURRENT_SNAPSHOT"
