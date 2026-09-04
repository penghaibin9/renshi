"""
hr_staff/policies/scope_policy.py —— 读路径 data scope 强制（P1-5）。

原则（总册 §6.2/§53）：先 tenant，再 data scope，再 permission，再字段策略。
COLLEGE/DEPARTMENT scope 用 HR02 组织子树解析；SELF/EXPLICIT_STAFF_SET 用 staff_ids；
其余未授权 scope fail-closed。
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone
from typing import Optional

from hr_staff.context import HrStaffRequestContext
from hr_staff.models import HrStaffMaster
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class StaffScopeDenied(Exception):
    code = "STAFF_SCOPE_DENIED"


class StaffNotFound(Exception):
    code = "STAFF_NOT_FOUND"


class ScopeEnforcer:
    """统一 data scope 判定（只读）。"""

    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id
        self.as_of = context.as_of or timezone.localdate()

    def get_staff_or_deny(self, staff_id) -> HrStaffMaster:
        staff = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff_id).first()
        if staff is None:
            raise StaffNotFound()
        self.assert_accessible(staff)
        return staff

    def assert_accessible(self, staff: HrStaffMaster):
        """校验 staff 在请求 scope 内可见；否则 StaffScopeDenied（fail-closed）。"""
        scope = self.context.scope
        if scope.scope_type == "SCHOOL":
            return
        if scope.scope_type in ("SELF", "EXPLICIT_STAFF_SET") and scope.staff_ids:
            if str(staff.id) not in {str(x) for x in scope.staff_ids}:
                raise StaffScopeDenied()
            return
        if scope.scope_type in ("COLLEGE", "DEPARTMENT") and scope.org_id:
            qs = EffectiveDatedQueryService(self.tenant_id)
            primary = qs.primary_assignment_as_of(staff.id, self.as_of)
            if primary is None or primary.organization_id is None:
                raise StaffScopeDenied()
            from hr_structure.selectors.effective import build_tree_as_of

            nodes = build_tree_as_of(self.tenant_id, scope.org_id, self.as_of, depth_limit=6)
            allowed = {n["id"] for n in nodes} | {scope.org_id}
            if primary.organization_id_id not in allowed:
                raise StaffScopeDenied()
            return
        # ASSIGNMENT / 未知 scope → fail-closed
        raise StaffScopeDenied()
