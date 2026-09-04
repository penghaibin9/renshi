"""
hr_changes/services/transfer_service.py —— 校内调动服务（S4，总册 §21）。

- create_transfer：transfer 专用创建（动作/字段目录校验 + HR02 容量预检）；
- validate_transfer：同校、目标组织/岗位有效、人员在职、岗位容量；
- current_vs_target：Before/After 对照数据（调动详情/向导 Step4）。

跨域生效（Apply）由 S8 Apply Service 调 HR03 domain service 完成，本服务不写 HR03。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.policies.transfer_policy import TransferPolicy
from hr_changes.services.change_service import (
    ChangeService,
    ChangeServiceError,
)
from hr_changes.integrations.hr02 import PositionGate


class TransferService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.policy = TransferPolicy(tenant_id)
        self.position_gate = PositionGate(tenant_id)

    # ------------------------------------------------------------------
    def create_transfer(
        self,
        *,
        staff_master_id,
        action_id,
        reason_id,
        requested_effective_at,
        target_org_id=None,
        target_position_id=None,
        source_org_id=None,
        source_position_id=None,
        fte=None,
        reporting_staff_id=None,
        priority: str = "NORMAL",
    ) -> HrPersonnelChangeCase:
        action = _load_action_safe(self.tenant_id, action_id)
        if not self.policy.is_transfer_action(action.code):
            raise ChangeServiceError(
                "CHANGE_INVALID_ACTION", f"{action.code} 不是校内调动动作"
            )

        proposals: list[dict] = []
        if "organization" in self.policy.allowed_fields(action.code):
            if not target_org_id:
                raise ChangeServiceError("CHANGE_TARGET_ORG_INVALID", "组织调动必须指定目标组织")
            proposals.append(
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(_pk(target_org_id)),
                    "proposed_value_display": _org_name(self.tenant_id, target_org_id) or str(_pk(target_org_id)),
                    "old_value_display": _org_name(self.tenant_id, source_org_id) if source_org_id else "",
                }
            )
        if "position" in self.policy.allowed_fields(action.code):
            if not target_position_id:
                raise ChangeServiceError("CHANGE_TARGET_POSITION_INVALID", "岗位调动必须指定目标岗位")
            proposals.append(
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "proposed_value_ref": str(_pk(target_position_id)),
                    "proposed_value_display": _position_code(self.tenant_id, target_position_id) or str(_pk(target_position_id)),
                    "old_value_display": _position_code(self.tenant_id, source_position_id) if source_position_id else "",
                }
            )
        if fte is not None:
            proposals.append(
                {
                    "domain": "assignment",
                    "field_code": "fte",
                    "proposed_value_ref": str(fte),
                    "proposed_value_display": str(fte),
                }
            )
        if reporting_staff_id:
            policy = self.policy.resolve_reporting_manager_policy(action, True)
            if policy == "SELECT_EXPLICIT":
                proposals.append(
                    {
                        "domain": "assignment",
                        "field_code": "reporting_staff",
                        "proposed_value_ref": str(_pk(reporting_staff_id)),
                        "proposed_value_display": str(_pk(reporting_staff_id)),
                    }
                )

        return ChangeService(self.tenant_id, actor_user_id=self.actor_user_id).create_case(
            staff_master_id=staff_master_id,
            action_id=action,
            reason_id=reason_id,
            requested_effective_at=requested_effective_at,
            proposals=proposals,
            source_org_id=source_org_id,
            target_org_id=target_org_id,
            source_position_id=source_position_id,
            target_position_id=target_position_id,
            priority=priority,
        )

    # ------------------------------------------------------------------
    def validate_transfer(self, case: HrPersonnelChangeCase) -> dict:
        """transfer 专用校验（返回 items/blockers/warnings）。"""
        blockers: list[dict] = []
        warnings: list[dict] = []

        # 同校（组织跨学校 → blocker）
        if case.source_org_id_id and case.target_org_id_id:
            self.policy.validate_same_school(case.source_org_id, case.target_org_id)

        # 目标组织有效
        if case.target_org_id and case.target_org_id.identity_status != "ACTIVE":
            blockers.append(
                {
                    "level": "BLOCKER",
                    "code": "CHANGE_TARGET_ORG_INVALID",
                    "message": "目标组织已停用",
                    "domain": "HR02",
                }
            )

        # 岗位容量（HR02）
        capacity = self.position_gate.check_capacity(case)
        blockers.extend(
            {
                "level": "BLOCKER",
                "code": b["code"],
                "message": b["message"],
                "domain": "HR02",
            }
            for b in capacity
        )

        # 人员在职（HR03）
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        status = EffectiveDatedQueryService(self.tenant_id).status_as_of(
            case.staff_master_id_id, timezone.localdate()
        )
        if status in ("DEPARTED", "DEPARTURE_PENDING", "RETIRED"):
            blockers.append(
                {
                    "level": "BLOCKER",
                    "code": "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                    "message": f"人员当前状态为「{status}」，不允许发起调动",
                    "domain": "HR03",
                }
            )

        # 直属关系策略（INFO）
        if case.action_id.code in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        ):
            warnings.append(
                {
                    "level": "WARNING",
                    "code": "REPORTING_MANAGER_POLICY",
                    "message": "调动后直属关系按策略推导（不自动复制原上级）",
                    "domain": "HR06",
                }
            )

        return {"items": blockers + warnings, "blockers": blockers, "warnings": warnings}

    # ------------------------------------------------------------------
    def current_vs_target(self, case: HrPersonnelChangeCase) -> dict:
        """Before/After 对照（调动详情/预览 Step4）。"""
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        qs = EffectiveDatedQueryService(self.tenant_id)
        current = qs.primary_assignment_as_of(case.staff_master_id_id, timezone.localdate())
        before = {
            "organization": (
                qs.org_name_as_of(case.source_org_id_id, timezone.localdate())
                if case.source_org_id_id
                else (current.organization_id.stable_code if current and current.organization_id else "")
            ),
            "position": (
                current.position_id.position_code if current and current.position_id else ""
            ),
            "fte": str(current.fte) if current else "",
        }
        after = {
            "organization": (
                qs.org_name_as_of(case.target_org_id_id, case.requested_effective_at)
                or (case.target_org_id.stable_code if case.target_org_id else "")
                if case.target_org_id_id
                else before["organization"]
            ),
            "position": (
                case.target_position_id.position_code if case.target_position_id else before["position"]
            ),
            "fte": (
                next(
                    (p.proposed_value_display for p in case.proposals.all() if p.field_code == "fte"),
                    before["fte"],
                )
            ),
        }
        return {"before": before, "after": after}


# ---------------------------------------------------------------------------
def _pk(value):
    return value.pk if hasattr(value, "pk") else value


def _load_action_safe(tenant_id, action_id):
    from hr_changes.models import HrChangeAction

    action = HrChangeAction.objects.filter(tenant_id=tenant_id, id=_pk(action_id)).first()
    if action is None:
        raise ChangeServiceError("CHANGE_INVALID_ACTION", "异动类型不存在")
    return action


def _org_name(tenant_id, org_id):
    from hr_structure.models import HrOrganization

    org = HrOrganization.objects.filter(tenant_id=tenant_id, id=_pk(org_id)).first()
    if org is None:
        return None
    from hr_structure.selectors.effective import org_version_as_of

    version = org_version_as_of(tenant_id, org.id, timezone.localdate())
    return version.name if version else org.stable_code


def _position_code(tenant_id, position_id):
    from hr_structure.models import HrPosition

    pos = HrPosition.objects.filter(tenant_id=tenant_id, id=_pk(position_id)).first()
    return pos.position_code if pos else None
