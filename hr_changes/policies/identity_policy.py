"""
hr_changes/policies/identity_policy.py —— 岗位与身份变更策略（S5，总册 §24/§25/§26）。

动作字段目录 + 用工性质变更策略 + 主岗/兼岗不变量说明。
"""

from __future__ import annotations

from hr_changes.constants import ChangeActionCode, EmploymentTypeChangePolicy

# 动作 → 允许的受管字段（Change Action Matrix §4）
IDENTITY_FIELD_MAP = {
    ChangeActionCode.POST_CATEGORY_CHANGE: {"post_catalog"},
    ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE: {"staff_category_code"},
    ChangeActionCode.EMPLOYMENT_TYPE_CHANGE: {"relationship_type", "employment_type"},
    ChangeActionCode.MANAGER_CHANGE: {"reporting_staff"},
    ChangeActionCode.LOCATION_CHANGE: {"location"},
    ChangeActionCode.ADD_SECONDARY_ASSIGNMENT: {"organization", "position", "fte"},
    ChangeActionCode.END_SECONDARY_ASSIGNMENT: {"effective_to"},
    ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH: {"organization", "position"},
}

# 需 HR07 合同复核的用工性质动作（follow-up）
EMPLOYMENT_TYPE_FOLLOWUP_HR07 = frozenset({ChangeActionCode.EMPLOYMENT_TYPE_CHANGE})

# 影响考勤/薪酬的下游域（WARNING 提示）
ATTENDANCE_PAYROLL_ACTIONS = frozenset(
    {
        ChangeActionCode.POST_CATEGORY_CHANGE,
        ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
        ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
    }
)


class IdentityPolicy:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def allowed_fields(self, action_code: str) -> set[str]:
        return IDENTITY_FIELD_MAP.get(action_code, set())

    def is_identity_action(self, action_code: str) -> bool:
        return action_code in IDENTITY_FIELD_MAP

    def resolve_employment_type_policy(self, action) -> str:
        """用工性质变更策略（总册 §25；默认 UPDATE_RELATIONSHIP）。"""
        followup = action.followup_policy_json or {}
        return followup.get(
            "employment_type_policy", EmploymentTypeChangePolicy.UPDATE_RELATIONSHIP
        )

    def validate_primary_invariant(self, action_code: str) -> None:
        """PRIMARY_ASSIGNMENT_SWITCH 的 one-primary 不变量说明（S8 Apply 由 HR03 switch_primary 保障）。"""
        from hr_changes.services.change_service import ChangeServiceError

        if action_code == ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH:
            # 不变量由 HR03 AssignmentService.switch_primary 的 DB 条件唯一 + 行锁双重保障
            return
