"""
hr_changes/services/identity_change_service.py —— 岗位与身份变更服务（S5，总册 §24/§25/§26）。

- create_identity_change：按动作生成 proposals 并创建 Case；
- change_matrix：变更矩阵（维度/当前/变更后/是否影响下游）供 UI 使用；
- validate_identity_change：动作字段必填校验 + 用工性质策略 + 主岗/兼岗不变量说明。

实际生效（写 HR03）由 S8 Apply Service 调 HR03 domain service 完成，本服务只请求改变。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.policies.identity_policy import IdentityPolicy
from hr_changes.services.change_service import (
    ChangeService,
    ChangeServiceError,
)
from hr_changes.services.transfer_service import _load_action_safe, _pk


class IdentityChangeService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.policy = IdentityPolicy(tenant_id)

    # ------------------------------------------------------------------
    def create_identity_change(
        self,
        *,
        staff_master_id,
        action_id,
        reason_id,
        requested_effective_at,
        proposals: list[dict],
        source_assignment_id=None,
        priority: str = "NORMAL",
    ) -> HrPersonnelChangeCase:
        action = _load_action_safe(self.tenant_id, action_id)
        if not self.policy.is_identity_action(action.code):
            raise ChangeServiceError(
                "CHANGE_INVALID_ACTION", f"{action.code} 不是岗位/身份变更动作"
            )
        allowed = self.policy.allowed_fields(action.code)
        for p in proposals:
            if p.get("field_code") not in allowed:
                raise ChangeServiceError(
                    "CHANGE_INVALID_PAYLOAD",
                    f"字段 {p.get('domain')}.{p.get('field_code')} 不允许在动作 {action.code} 中使用",
                )
        # 兼岗动作：禁止覆盖主岗（增加兼岗必须 is_secondary 语义；V1 通过 action 本身保证）
        if action.code == ChangeActionCode.ADD_SECONDARY_ASSIGNMENT:
            has_org = any(p.get("field_code") == "organization" for p in proposals)
            has_pos = any(p.get("field_code") == "position" for p in proposals)
            if not (has_org and has_pos):
                raise ChangeServiceError(
                    "CHANGE_INVALID_PAYLOAD", "增加兼岗必须指定目标组织与岗位"
                )

        return ChangeService(self.tenant_id, actor_user_id=self.actor_user_id).create_case(
            staff_master_id=staff_master_id,
            action_id=action,
            reason_id=reason_id,
            requested_effective_at=requested_effective_at,
            proposals=proposals,
            source_assignment_id=source_assignment_id,
            priority=priority,
        )

    # ------------------------------------------------------------------
    def change_matrix(self, case: HrPersonnelChangeCase) -> list[dict]:
        """变更矩阵（维度/当前/变更后/是否影响下游）（总册 §24.2）。"""
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        qs = EffectiveDatedQueryService(self.tenant_id)
        staff_id = case.staff_master_id_id
        staff = case.staff_master_id
        current = qs.primary_assignment_as_of(staff_id, date.today())
        proposals = {p.field_code: p for p in case.proposals.all()}

        def _val(field_code, fallback=""):
            p = proposals.get(field_code)
            return p.proposed_value_display if p else fallback

        matrix = []
        staff_category = staff.staff_category_code
        rel = qs.relationships_as_of(staff_id, date.today()).first()
        rel_type = rel.relationship_type if rel else ""

        matrix.append(
            {
                "dimension": "岗位类别",
                "current": current.post_catalog_id.name if current and current.post_catalog_id else "",
                "after": _val("post_catalog", "未变更"),
                "affectsDownstream": case.action_id.code == ChangeActionCode.POST_CATEGORY_CHANGE,
            }
        )
        matrix.append(
            {
                "dimension": "人员类别",
                "current": staff_category or "",
                "after": _val("staff_category_code", staff_category or "未变更"),
                "affectsDownstream": case.action_id.code == ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
            }
        )
        matrix.append(
            {
                "dimension": "用工性质",
                "current": rel_type or "",
                "after": _val("relationship_type", rel_type or "未变更"),
                "affectsDownstream": case.action_id.code == ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
            }
        )
        matrix.append(
            {
                "dimension": "直属上级",
                "current": current.reporting_staff_id.person_id.legal_name
                if current and current.reporting_staff_id else "",
                "after": _val("reporting_staff", "未变更"),
                "affectsDownstream": case.action_id.code == ChangeActionCode.MANAGER_CHANGE,
            }
        )
        matrix.append(
            {
                "dimension": "工作地点",
                "current": "",
                "after": _val("location", "未变更"),
                "affectsDownstream": case.action_id.code == ChangeActionCode.LOCATION_CHANGE,
            }
        )
        # 兼岗/主岗维度
        if case.action_id.code in (
            ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
            ChangeActionCode.END_SECONDARY_ASSIGNMENT,
            ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
        ):
            matrix.append(
                {
                    "dimension": "主岗/兼岗",
                    "current": f"{current.organization_id.stable_code if current and current.organization_id else ''}",
                    "after": case.action_id.name,
                    "affectsDownstream": True,
                }
            )
        return matrix

    # ------------------------------------------------------------------
    def validate_identity_change(self, case: HrPersonnelChangeCase) -> dict:
        blockers: list[dict] = []
        warnings: list[dict] = []

        action_code = case.action_id.code
        required = {
            ChangeActionCode.POST_CATEGORY_CHANGE: ["post_catalog"],
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE: ["staff_category_code"],
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE: ["relationship_type"],
            ChangeActionCode.MANAGER_CHANGE: ["reporting_staff"],
            ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH: ["organization", "position"],
        }.get(action_code, [])
        present = {p.field_code for p in case.proposals.all()}
        for field in required:
            if field not in present:
                blockers.append(
                    {
                        "level": "BLOCKER",
                        "code": "CHANGE_INVALID_PAYLOAD",
                        "message": f"缺少必填变更字段 {field}",
                        "domain": "HR06",
                    }
                )

        if action_code == ChangeActionCode.EMPLOYMENT_TYPE_CHANGE:
            policy = self.policy.resolve_employment_type_policy(case.action_id)
            if policy == "REQUIRE_HR07_CONTRACT":
                warnings.append(
                    {
                        "level": "WARNING",
                        "code": "CONTRACT_REVIEW_REQUIRED",
                        "message": "用工性质变更需 HR07 合同变更配合",
                        "domain": "HR07",
                    }
                )

        if action_code == ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH:
            warnings.append(
                {
                    "level": "WARNING",
                    "code": "PRIMARY_INVARIANT",
                    "message": "主岗切换保证任意时刻唯一主岗（HR03 DB 约束 + 行锁）",
                    "domain": "HR03",
                }
            )

        return {"items": blockers + warnings, "blockers": blockers, "warnings": warnings}
