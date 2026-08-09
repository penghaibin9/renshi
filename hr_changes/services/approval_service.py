"""
hr_changes/services/approval_service.py —— 审批流解析与审批快照（S3，总册 §19/§20）。

- Workflow Resolver：按 action/reason/scope 生成审批链，禁止写死单一 source→target→HR；
  V1 支持可配置链：跨组织调动 SOURCE_ORG → TARGET_ORG → SCHOOL_HR。
- 审批流程配置后续变化不能改变已提交案件（HrChangeApprovalSnapshot 冻结）。
- approve_step / final approve 由 ChangeService 调用本服务判断是否全部步骤完成。
"""

from __future__ import annotations

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrChangeApprovalSnapshot, HrPersonnelChangeCase


class ApprovalServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ApprovalService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Workflow Resolver（V1：action/reason/scope 派发；学校可配置）
    # ------------------------------------------------------------------
    def resolve_steps(self, case: HrPersonnelChangeCase) -> list[dict]:
        action_code = case.action_id.code
        target_org = case.target_org_id_id
        source_org = case.source_org_id_id

        if action_code in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        ) and (target_org or source_org):
            steps = []
            if source_org:
                steps.append({"step_no": 1, "approver_scope": "SOURCE_ORG", "org_id": str(source_org)})
            if target_org:
                steps.append({"step_no": len(steps) + 1, "approver_scope": "TARGET_ORG", "org_id": str(target_org)})
            steps.append({"step_no": len(steps) + 1, "approver_scope": "SCHOOL_HR", "org_id": ""})
            return steps

        # 默认：学校人事审批
        return [{"step_no": 1, "approver_scope": "SCHOOL_HR", "org_id": ""}]

    def build_workflow(self, case: HrPersonnelChangeCase) -> HrChangeApprovalSnapshot:
        """冻结审批快照（已提交案件不可再变）。"""
        steps = self.resolve_steps(case)
        latest = (
            HrChangeApprovalSnapshot.objects.filter(change_case_id=case)
            .order_by("-workflow_version")
            .first()
        )
        workflow_version = (latest.workflow_version + 1) if latest else 1
        for idx, step in enumerate(steps):
            step["status"] = "PENDING"
            step["approved_by"] = None
        snapshot = HrChangeApprovalSnapshot.objects.create(
            change_case_id=case,
            workflow_version=workflow_version,
            steps_json=steps,
        )
        case.approval_instance_id = str(snapshot.id)
        case.save(update_fields=["approval_instance_id", "updated_at"])
        return snapshot

    # ------------------------------------------------------------------
    # 步骤推进（ChangeService.approve 调用）
    # ------------------------------------------------------------------
    def get_current_snapshot(self, case: HrPersonnelChangeCase) -> HrChangeApprovalSnapshot:
        if not case.approval_instance_id:
            raise ApprovalServiceError("CHANGE_APPROVAL_SNAPSHOT_MISMATCH", "案件缺少审批快照")
        snap = (
            HrChangeApprovalSnapshot.objects.filter(
                change_case_id=case, id=case.approval_instance_id
            )
            .first()
        )
        if snap is None:
            raise ApprovalServiceError("CHANGE_APPROVAL_SNAPSHOT_MISMATCH", "审批快照不存在")
        return snap

    def current_step(self, case: HrPersonnelChangeCase) -> dict | None:
        snap = self.get_current_snapshot(case)
        for step in snap.steps_json:
            if step.get("status") == "PENDING":
                return step
        return None

    def approve_current_step(self, case: HrPersonnelChangeCase, actor_user_id) -> bool:
        """批准当前步骤；返回是否全部完成（True=可 final approve）。"""
        snap = self.get_current_snapshot(case)
        pending = next((s for s in snap.steps_json if s.get("status") == "PENDING"), None)
        if pending is None:
            return True
        pending["status"] = "APPROVED"
        pending["approved_by"] = actor_user_id
        snap.save(update_fields=["steps_json"])
        return all(s.get("status") == "APPROVED" for s in snap.steps_json)

    def reject_current_step(self, case: HrPersonnelChangeCase, actor_user_id) -> None:
        snap = self.get_current_snapshot(case)
        pending = next((s for s in snap.steps_json if s.get("status") == "PENDING"), None)
        if pending is None:
            return
        pending["status"] = "REJECTED"
        pending["rejected_by"] = actor_user_id
        snap.save(update_fields=["steps_json"])
