"""
hr_changes/services/return_service.py —— 临时异动返岗服务（S6，总册 §28/§30）。

- plan_return：生成 RETURN_FROM_TEMPORARY Case（审批后执行）；
- check_source_position_valid：原岗仍有效（HR02）否则 RETURN_TARGET_INVALID → 人工解决；
- execute_return：关闭临时任职段、按 source_policy 恢复/调整原岗、更新 link。

跨域写一律经 HR03 domain service（AssignmentService），禁止直接 UPDATE。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import ChangeActionCode, SourceAssignmentPolicy
from hr_changes.models import HrPersonnelChangeCase, HrTemporaryAssignmentLink
from hr_changes.services.change_service import ChangeService, ChangeServiceError


class ReturnServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ReturnService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _get_link_or_deny(self, link_id) -> HrTemporaryAssignmentLink:
        link = (
            HrTemporaryAssignmentLink.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=link_id)
            .first()
        )
        if link is None:
            raise ReturnServiceError("CHANGE_NOT_FOUND", "临时异动关系不存在")
        return link

    # ------------------------------------------------------------------
    def check_source_position_valid(self, link: HrTemporaryAssignmentLink) -> tuple[bool, Optional[str]]:
        """原岗仍有效？HR02 岗位生命周期必须 ACTIVE。"""
        source = link.source_assignment_id
        position = source.position_id
        if position is None:
            return True, None  # 无权威岗位（legacy 映射）→ 视为可返
        if position.lifecycle_status != "ACTIVE":
            return False, "RETURN_TARGET_INVALID"
        return True, None

    # ------------------------------------------------------------------
    @transaction.atomic
    def plan_return(self, link_id, *, requested_effective_at: Optional[date] = None) -> HrPersonnelChangeCase:
        """生成 RETURN_FROM_TEMPORARY Case（返岗仍需审批；原岗无效时进入 exception flow）。"""
        link = self._get_link_or_deny(link_id)
        if link.status not in ("ACTIVE", "EXTENDED"):
            raise ReturnServiceError("CHANGE_INVALID_STATE", "仅生效中的临时异动可计划返岗")
        ok, error = self.check_source_position_valid(link)
        if not ok:
            link.status = HrTemporaryAssignmentLink.Status.RETURN_TARGET_INVALID
            link.version += 1
            link.save(update_fields=["status", "version", "updated_at"])
            raise ReturnServiceError(
                "RETURN_TARGET_INVALID",
                "原岗位已撤销/关闭，不能自动返岗；需人工指定新返岗目标后再审批",
            )
        action = _return_action(self.tenant_id)
        reason = _return_reason(self.tenant_id)
        case = ChangeService(self.tenant_id, actor_user_id=self.actor_user_id).create_case(
            staff_master_id=link.change_case_id.staff_master_id,
            action_id=action,
            reason_id=reason,
            requested_effective_at=requested_effective_at or date.today(),
            proposals=[],
        )
        link.return_case_id = case
        link.version += 1
        link.save(update_fields=["return_case_id", "version", "updated_at"])
        return case

    # ------------------------------------------------------------------
    @transaction.atomic
    def execute_return(
        self,
        link_id,
        *,
        return_effective_at: date,
        return_case_id=None,
    ) -> HrTemporaryAssignmentLink:
        """返岗执行（S8 Apply 调用；V1 支持 KEEP_ACTIVE/SUSPEND/REDUCE_FTE 语义）。"""
        link = self._get_link_or_deny(link_id)
        if link.status not in ("ACTIVE", "EXTENDED"):
            raise ReturnServiceError("CHANGE_INVALID_STATE", "仅生效中的临时异动可返岗")

        source = link.source_assignment_id
        temporary = link.temporary_assignment_id

        # 1) 关闭临时任职段（HR03 domain service）
        from hr_staff.services.assignment_service import AssignmentService, AssignmentPolicyViolation

        assignment_service = AssignmentService(
            self.tenant_id, audit_actor_user_id=self.actor_user_id
        )
        try:
            assignment_service.close_assignment(
                assignment_id=temporary.id,
                effective_to=return_effective_at,
                reason_code="HR06_RETURN_FROM_TEMPORARY",
                source_business_type="HR06_POSITION_CHANGE",
                source_business_id=str(link.change_case_id_id),
            )
        except AssignmentPolicyViolation as exc:
            raise ReturnServiceError(exc.code or "CHANGE_INVALID_STATE", exc.args[0] if exc.args else "临时任职关闭失败")

        # 2) 按 source_policy 恢复原岗（V1：KEEP_ACTIVE 无需写；SUSPEND/REDUCE 通过 HR03 create_assignment 恢复）
        policy = link.source_assignment_status_policy
        if policy in (SourceAssignmentPolicy.SUSPEND, SourceAssignmentPolicy.REDUCE_FTE):
            self._restore_source(assignment_service, link, return_effective_at)

        # 3) 更新 link
        link.status = HrTemporaryAssignmentLink.Status.RETURNED
        if return_case_id:
            link.return_case_id_id = return_case_id
        link.version += 1
        link.save(update_fields=["status", "return_case_id", "version", "updated_at"])
        return link

    def _restore_source(self, assignment_service, link, return_effective_at):
        """SUSPEND/REDUCE_FTE：在返岗日经 HR03 恢复原岗主任职段。"""
        source = link.source_assignment_id
        # 若 source 段仍开放（KEEP 场景误用）则先关闭
        if source.effective_to is None:
            assignment_service.close_assignment(
                assignment_id=source.id,
                effective_to=return_effective_at,
                reason_code="HR06_RESTORE_SOURCE_END",
                source_business_type="HR06_POSITION_CHANGE",
                source_business_id=str(link.change_case_id_id),
            )
        from hr_staff.services.assignment_service import AssignmentPolicyViolation

        try:
            assignment_service.create_assignment(
                employment_relationship_id=source.employment_relationship_id,
                assignment_type="PRIMARY",
                effective_from=return_effective_at,
                organization_id=source.organization_id,
                position_id=source.position_id,
                post_catalog_id=source.post_catalog_id,
                legacy_department_id=source.legacy_department_id,
                legacy_job_position_id=source.legacy_job_position_id,
                assignment_role_code=source.assignment_role_code,
                fte=source.fte,
                reporting_staff_id=source.reporting_staff_id,
                source_business_type="HR06_POSITION_CHANGE",
                source_business_id=str(link.change_case_id_id),
            )
        except AssignmentPolicyViolation as exc:
            raise ReturnServiceError(
                exc.code or "CHANGE_INVALID_STATE",
                exc.args[0] if exc.args else "原岗恢复失败",
            )


def _return_action(tenant_id):
    from hr_changes.models import HrChangeAction

    action = HrChangeAction.objects.filter(
        tenant_id=tenant_id, code=ChangeActionCode.RETURN_FROM_TEMPORARY
    ).first()
    if action is None:
        raise ChangeServiceError("CHANGE_INVALID_ACTION", "返岗动作未配置")
    return action


def _return_reason(tenant_id):
    from hr_changes.models import HrChangeReason

    reason = HrChangeReason.objects.filter(
        tenant_id=tenant_id,
        action_code=ChangeActionCode.RETURN_FROM_TEMPORARY,
        code="TEMPORARY_PERIOD_END",
    ).first()
    if reason is None:
        raise ChangeServiceError("CHANGE_INVALID_REASON", "返岗原因未配置")
    return reason
