"""
hr_changes/policies/transfer_policy.py —— 校内调动策略（S4，总册 §21/§22）。

- 三种转移动作的字段定义（ORG_TRANSFER/POSITION_TRANSFER/ORG_POSITION_TRANSFER）；
- Reporting Manager Policy 解析（KEEP / DERIVE_FROM_TARGET_ORG / SELECT_EXPLICIT）；
- 调动前提：同校、目标组织/岗位有效、人员在职。
"""

from __future__ import annotations

from hr_changes.constants import ChangeActionCode, ReportingManagerPolicy


class TransferPolicy:
    """V1 校内调动策略（可配置来源：action.effective_date_rule_json 等）。"""

    # 动作 → 受管字段（Change Action Matrix §4）
    FIELD_MAP = {
        ChangeActionCode.ORG_TRANSFER: {"organization"},
        ChangeActionCode.POSITION_TRANSFER: {"position"},
        ChangeActionCode.ORG_POSITION_TRANSFER: {"organization", "position"},
    }

    # 动作 → 变更语义
    #  - organization: 目标组织
    #  - position: 目标岗位（需 HR02 容量校验）
    #  - fte: 目标工作量
    #  - reporting_staff: 直属上级（显式选择时）
    ALLOWED_PROPOSAL_FIELDS = {
        ChangeActionCode.ORG_TRANSFER: {"organization", "fte", "reporting_staff"},
        ChangeActionCode.POSITION_TRANSFER: {"position", "fte", "reporting_staff"},
        ChangeActionCode.ORG_POSITION_TRANSFER: {"organization", "position", "fte", "reporting_staff"},
    }

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def allowed_fields(self, action_code: str) -> set[str]:
        return self.ALLOWED_PROPOSAL_FIELDS.get(action_code, set())

    def is_transfer_action(self, action_code: str) -> bool:
        return action_code in self.FIELD_MAP

    def resolve_reporting_manager_policy(
        self, action, proposed_reporting_staff_provided: bool
    ) -> str:
        """按 action 配置与用户是否显式选择决定直属策略（总册 §22）。"""
        if proposed_reporting_staff_provided:
            return ReportingManagerPolicy.SELECT_EXPLICIT
        return action.reporting_manager_policy or ReportingManagerPolicy.KEEP

    def validate_same_school(self, source_org, target_org) -> None:
        """校内调动必须同一学校内（tenant 由服务层保证；此处校验同一组织维度）。"""
        if source_org and target_org and source_org.tenant_id != target_org.tenant_id:
            from hr_changes.services.change_service import ChangeServiceError

            raise ChangeServiceError(
                "CHANGE_TARGET_ORG_INVALID", "跨学校调动不在校内调动范围内（请走调出/离校流程）"
            )
