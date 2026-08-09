"""
hr_changes/services/change_service.py —— 异动案件生命周期服务（S3，总册 §17/§10）。

职责：
- create_case / update_draft / submit / withdraw / cancel / return / resubmit；
- 所有状态转移经 services/state_machine.py + 写 HrChangeTransition；
- 乐观并发：version 递增 + 请求携带 If-Match/version 冲突抛 VERSION_CONFLICT；
- 审批并发重检：submit/approve 必须重新校验 impact（BLOCKER 不因陈旧快照放行）。

禁止：裸改 status；DELETE 正式案件。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import (
    CASE_ACTIVE_STATUSES,
    CHANGE_FIELD_CATALOG,
    CaseStatus,
)
from hr_changes.models import (
    HrChangeProposal,
    HrChangeReason,
    HrChangeTransition,
    HrPersonnelChangeCase,
)
from hr_changes.services.case_number_service import CaseNumberService
from hr_changes.services.state_machine import ChangeStateError, transition


def _current_step_no(approval, case) -> int:
    """当前待处理步骤号（供文案使用）。"""
    try:
        step = approval.current_step(case)
        return step.get("step_no", 1) if step else 1
    except Exception:
        return 1


class ChangeServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ChangeService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 查询辅助（tenant fail-closed）
    # ------------------------------------------------------------------
    def _get_case_or_deny(self, case_id) -> HrPersonnelChangeCase:
        case = (
            HrPersonnelChangeCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=_norm_id(case_id))
            .first()
        )
        if case is None:
            raise ChangeServiceError("CHANGE_NOT_FOUND", "异动案件不存在")
        return case

    @staticmethod
    def _assert_version(case: HrPersonnelChangeCase, expected_version: Optional[int]):
        if expected_version is not None and case.version != expected_version:
            raise ChangeServiceError(
                "VERSION_CONFLICT", "案件已被他人修改，请刷新后重试"
            )

    def _record_transition(
        self,
        case: HrPersonnelChangeCase,
        from_status: str,
        to_status: str,
        action: str,
        *,
        comment: str = "",
        request_id: str = "",
    ) -> None:
        HrChangeTransition.objects.create(
            change_case_id=case,
            tenant_id=self.tenant_id,
            from_status=from_status,
            to_status=to_status,
            action=action,
            actor_id=self.actor_user_id,
            comment=comment,
            request_id=request_id,
        )

    def _apply_transition(
        self,
        case: HrPersonnelChangeCase,
        action: str,
        to_status: str,
        *,
        comment: str = "",
        request_id: str = "",
        version: Optional[int] = None,
        **save_fields,
    ) -> HrPersonnelChangeCase:
        """原子应用状态转移：校验 → 更新 → 审计 transition → version++。"""
        self._assert_version(case, version)
        target = transition(action, case.status, to_status)
        from_status = case.status
        case.status = target
        case.version += 1
        for k, v in save_fields.items():
            setattr(case, k, v)
        case.save(update_fields=["status", "version", "updated_at", *save_fields.keys()])
        self._record_transition(
            case, from_status, target, action, comment=comment, request_id=request_id
        )
        return case

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    @transaction.atomic
    def create_case(
        self,
        *,
        staff_master_id,
        action_id,
        reason_id,
        requested_effective_at: date,
        proposals: list[dict],
        source_org_id=None,
        target_org_id=None,
        source_position_id=None,
        target_position_id=None,
        source_assignment_id=None,
        priority: str = "NORMAL",
        version: Optional[int] = None,
    ) -> HrPersonnelChangeCase:
        action = _load_action(self.tenant_id, _norm_id(action_id))
        if not action.enabled:
            raise ChangeServiceError("CHANGE_INVALID_ACTION", "该异动类型已停用")
        reason = _load_reason(self.tenant_id, _norm_id(reason_id))
        if reason.action_code != action.code:
            raise ChangeServiceError(
                "CHANGE_INVALID_REASON",
                f"原因 {reason.code} 不属于动作 {action.code}",
            )
        effective_at = _parse_effective_date(requested_effective_at)
        _validate_effective_date(action, effective_at)

        staff = _load_staff(self.tenant_id, staff_master_id)
        source_org = _load_org_or_none(self.tenant_id, source_org_id)
        target_org = _load_org_or_none(self.tenant_id, target_org_id)
        source_pos = _load_position_or_none(self.tenant_id, source_position_id)
        target_pos = _load_position_or_none(self.tenant_id, target_position_id)

        case_no = CaseNumberService(self.tenant_id).allocate()
        case = HrPersonnelChangeCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=case_no,
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=effective_at,
            source_org_id=source_org,
            target_org_id=target_org,
            source_position_id=source_pos,
            target_position_id=target_pos,
            source_assignment_id=_resolve_assignment_or_none(self.tenant_id, source_assignment_id),
            priority=priority,
            initiator_id=self.actor_user_id,
            owner_id=self.actor_user_id,
            status=CaseStatus.DRAFT,
        )
        self._create_proposals(case, proposals)
        self._record_transition(
            case, "", CaseStatus.DRAFT, "create", request_id=""
        )
        return case

    def _create_proposals(self, case: HrPersonnelChangeCase, proposals: list[dict]):
        for p in proposals:
            domain = p.get("domain")
            field_code = p.get("field_code")
            if domain not in CHANGE_FIELD_CATALOG:
                raise ChangeServiceError("CHANGE_INVALID_PAYLOAD", f"非法字段域: {domain}")
            if field_code not in CHANGE_FIELD_CATALOG[domain]:
                raise ChangeServiceError(
                    "CHANGE_INVALID_PAYLOAD", f"字段 {domain}.{field_code} 不在受管目录"
                )
            HrChangeProposal.objects.create(
                change_case_id=case,
                domain=domain,
                field_code=field_code,
                old_value_ref=p.get("old_value_ref", ""),
                old_value_display=p.get("old_value_display", ""),
                proposed_value_ref=p.get("proposed_value_ref", ""),
                proposed_value_display=p.get("proposed_value_display", ""),
                effective_at=case.requested_effective_at,
                source_fact_id=p.get("source_fact_id", ""),
                metadata_json=p.get("metadata_json", {}),
            )

    # ------------------------------------------------------------------
    # 草稿编辑
    # ------------------------------------------------------------------
    @transaction.atomic
    def update_draft(
        self,
        case_id,
        *,
        version: Optional[int] = None,
        reason_id=None,
        requested_effective_at: Optional[date] = None,
        target_org_id=None,
        target_position_id=None,
        priority=None,
    ) -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.DRAFT:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅草稿可编辑")
        self._assert_version(case, version)
        if reason_id is not None:
            reason = _load_reason(self.tenant_id, reason_id)
            if reason.action_code != case.action_id.code:
                raise ChangeServiceError("CHANGE_INVALID_REASON", "原因与动作不匹配")
            case.reason_id = reason
        if requested_effective_at is not None:
            parsed = _parse_effective_date(requested_effective_at)
            _validate_effective_date(case.action_id, parsed)
            case.requested_effective_at = parsed
        if target_org_id is not None:
            case.target_org_id_id = target_org_id
        if target_position_id is not None:
            case.target_position_id_id = target_position_id
        if priority is not None:
            case.priority = priority
        case.version += 1
        case.save()
        self._record_transition(case, CaseStatus.DRAFT, CaseStatus.DRAFT, "save_draft")
        return case

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------
    @transaction.atomic
    def submit(
        self, case_id, *, version: Optional[int] = None, request_id: str = "",
    ) -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        # 并发控制：先校验版本，再校验状态（stale 提交返回 VERSION_CONFLICT）
        self._assert_version(case, version)
        if case.status not in (CaseStatus.DRAFT, CaseStatus.READY_TO_SUBMIT):
            raise ChangeServiceError("CHANGE_INVALID_STATE", "当前状态不可提交")
        # 提交前必须通过 impact 校验（审批并发重检的入口闸门）
        from hr_changes.services.impact_service import ImpactService

        blockers = ImpactService(self.tenant_id).check_blockers(case)
        if blockers:
            raise ChangeServiceError(
                "CHANGE_POSITION_CAPACITY_CONFLICT",
                "存在阻断项：" + "; ".join(b["message"] for b in blockers),
            )
        case = self._apply_transition(
            case, "submit", CaseStatus.SUBMITTED,
            comment="提交", request_id=request_id,
            submitted_at=timezone.now(),
        )
        return case

    # ------------------------------------------------------------------
    # 撤回 / 取消
    # ------------------------------------------------------------------
    @transaction.atomic
    def withdraw(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status not in (CaseStatus.DRAFT, CaseStatus.READY_TO_SUBMIT, CaseStatus.SUBMITTED, CaseStatus.RETURNED):
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅发起人可撤回未生效案件")
        return self._apply_transition(case, "withdraw", CaseStatus.WITHDRAWN, comment=comment)

    @transaction.atomic
    def cancel(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status not in CASE_ACTIVE_STATUSES or case.status == CaseStatus.APPLYING:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "当前状态不可取消")
        return self._apply_transition(case, "cancel", CaseStatus.CANCELLED, comment=comment)

    # ------------------------------------------------------------------
    # 退回 / 重新提交
    # ------------------------------------------------------------------
    @transaction.atomic
    def return_case(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.UNDER_APPROVAL:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅审批中可退回")
        case = self._apply_transition(
            case, "return", CaseStatus.RETURNED, comment=comment or "退回补充"
        )
        return case

    @transaction.atomic
    def resubmit(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.RETURNED:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅已退回案件可重新提交")
        from hr_changes.services.impact_service import ImpactService

        blockers = ImpactService(self.tenant_id).check_blockers(case)
        if blockers:
            raise ChangeServiceError(
                "CHANGE_POSITION_CAPACITY_CONFLICT",
                "存在阻断项：" + "; ".join(b["message"] for b in blockers),
            )
        return self._apply_transition(
            case, "resubmit", CaseStatus.RESUBMITTED, comment=comment or "重新提交"
        )

    # ------------------------------------------------------------------
    # 启动审批（提交后由 HR06-01 处理）
    # ------------------------------------------------------------------
    @transaction.atomic
    def start_approval(self, case_id, *, version: Optional[int] = None) -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status not in (CaseStatus.SUBMITTED, CaseStatus.RESUBMITTED):
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅已提交案件可进入审批")
        from hr_changes.services.approval_service import ApprovalService

        ApprovalService(self.tenant_id).build_workflow(case)
        return self._apply_transition(case, "enter_approval", CaseStatus.UNDER_APPROVAL)

    # ------------------------------------------------------------------
    # 批准 / 驳回（审批并发重检：锁行 + 状态重验 + impact 重检 + 步骤推进）
    # ------------------------------------------------------------------
    @transaction.atomic
    def approve(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.UNDER_APPROVAL:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅审批中可批准")
        # 并发重检：审批时重新计算 blockers（不依赖提交时旧快照）
        from hr_changes.services.impact_service import ImpactService

        blockers = ImpactService(self.tenant_id).check_blockers(case)
        if blockers:
            raise ChangeServiceError(
                "CHANGE_POSITION_CAPACITY_CONFLICT",
                "审批重检发现阻断项：" + "; ".join(b["message"] for b in blockers),
            )
        from hr_changes.services.approval_service import ApprovalService

        approval = ApprovalService(self.tenant_id)
        all_done = approval.approve_current_step(case, self.actor_user_id)
        if not all_done:
            return self._apply_transition(
                case, "approve_step", CaseStatus.UNDER_APPROVAL,
                comment=comment or f"步骤{_current_step_no(approval, case)}已批准",
            )
        return self._apply_transition(
            case, "approve", CaseStatus.APPROVED_WAITING_EFFECTIVE,
            comment=comment or "全部审批完成",
            approved_at=timezone.now(),
            approved_effective_at=case.requested_effective_at,
        )

    @transaction.atomic
    def reject(self, case_id, *, version: Optional[int] = None, comment: str = "") -> HrPersonnelChangeCase:
        case = self._get_case_or_deny(case_id)
        if case.status != CaseStatus.UNDER_APPROVAL:
            raise ChangeServiceError("CHANGE_INVALID_STATE", "仅审批中可驳回")
        from hr_changes.services.approval_service import (
            ApprovalService,
            ApprovalServiceError,
        )

        try:
            ApprovalService(self.tenant_id).reject_current_step(case, self.actor_user_id)
        except ApprovalServiceError:
            pass  # 无快照时仅记录驳回
        return self._apply_transition(
            case, "reject", CaseStatus.REJECTED, comment=comment or "驳回"
        )


# ---------------------------------------------------------------------------
# 模块级辅助
# ---------------------------------------------------------------------------
def _norm_id(value):
    """模型实例 → pk；UUID/字符串原样返回（对齐 HR03 _assert_relationship_tenant 归一）。"""
    if value is not None and hasattr(value, "pk") and not isinstance(value, (str, int)):
        return value.pk
    return value


def _parse_effective_date(value) -> date:
    """接受 date 或 ISO 字符串（API 入参）。"""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        from django.utils.dateparse import parse_date

        parsed = parse_date(value)
        if parsed is None:
            raise ChangeServiceError("CHANGE_EFFECTIVE_DATE_INVALID", f"无效生效日期: {value}")
        return parsed
    raise ChangeServiceError("CHANGE_EFFECTIVE_DATE_INVALID", "生效日期格式不合法")


def _load_staff(tenant_id, staff_id):
    from hr_staff.models import HrStaffMaster

    staff = HrStaffMaster.objects.filter(tenant_id=tenant_id, id=_norm_id(staff_id)).first()
    if staff is None:
        raise ChangeServiceError("STAFF_NOT_FOUND", "教职工不存在或不属于当前学校")
    return staff


def _load_org_or_none(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_structure.models import HrOrganization

    org = HrOrganization.objects.filter(tenant_id=tenant_id, id=_norm_id(value)).first()
    if org is None:
        raise ChangeServiceError("CHANGE_TARGET_ORG_INVALID", "组织不存在或不属于当前学校")
    return org


def _load_position_or_none(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_structure.models import HrPosition

    pos = HrPosition.objects.filter(tenant_id=tenant_id, id=_norm_id(value)).first()
    if pos is None:
        raise ChangeServiceError("CHANGE_TARGET_POSITION_INVALID", "岗位不存在或不属于当前学校")
    return pos


def _resolve_assignment_or_none(tenant_id, value):
    """source_assignment 归一：实例→实例；UUID/字符串→tenant 校验后取实例；空→None。"""
    if value in (None, ""):
        return None
    from hr_staff.models import HrStaffAssignment

    if hasattr(value, "pk"):
        if value.tenant_id != tenant_id:
            raise ChangeServiceError("CHANGE_SOURCE_ASSIGNMENT_MISMATCH", "任职段不属于当前学校")
        return value
    assignment = HrStaffAssignment.objects.filter(
        tenant_id=tenant_id, id=_norm_id(value)
    ).first()
    if assignment is None:
        raise ChangeServiceError("CHANGE_SOURCE_ASSIGNMENT_MISMATCH", "任职段不存在或不属于当前学校")
    return assignment


def _load_action(tenant_id, action_id):
    from hr_changes.models import HrChangeAction

    action = HrChangeAction.objects.filter(tenant_id=tenant_id, id=_norm_id(action_id)).first()
    if action is None:
        raise ChangeServiceError("CHANGE_INVALID_ACTION", "异动类型不存在")
    return action


def _load_reason(tenant_id, reason_id):
    reason = HrChangeReason.objects.filter(tenant_id=tenant_id, id=_norm_id(reason_id)).first()
    if reason is None:
        raise ChangeServiceError("CHANGE_INVALID_REASON", "异动原因不存在")
    return reason


def _validate_effective_date(action, effective_at: date):
    """按 action.effective_date_rule_json 校验生效日期（V1 默认不允许过去日期）。"""
    rule = action.effective_date_rule_json or {}
    if effective_at is None:
        raise ChangeServiceError("CHANGE_EFFECTIVE_DATE_INVALID", "生效日期必填")
    allow_past = bool(rule.get("allow_past", False))
    if not allow_past and effective_at < date.today():
        raise ChangeServiceError(
            "CHANGE_EFFECTIVE_DATE_INVALID", "生效日期不能早于今天"
        )
    max_days = rule.get("max_days_from_today")
    if max_days:
        from datetime import timedelta

        if effective_at > date.today() + timedelta(days=int(max_days)):
            raise ChangeServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID", f"生效日期不能超过 {max_days} 天"
            )
