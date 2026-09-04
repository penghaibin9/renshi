"""
hr10_development/services/approval_service.py

审批工作流服务（总册 §49-51）。

多步骤审批推进：UNDER_MANAGER_REVIEW → UNDER_COLLEGE_REVIEW → UNDER_HR_REVIEW → UNDER_BUDGET_REVIEW → APPROVED
RETURNED ≠ REJECTED；禁止自审批；审批时写不可变 ApprovalSnapshot。
"""

import hashlib
import json
from datetime import datetime, timezone

from django.db import transaction

from hr10_development.constants import (
    RequestLifecycleStatus,
    DevelopmentErrorCode,
)
from hr10_development.models.approval_snapshot import HrDevelopmentApprovalSnapshot


class ApprovalService:
    """多步审批推进服务。"""

    # 审批步骤顺序（由 WorkflowPolicyVersion 决定；此处为默认链）
    DEFAULT_STEPS = [
        ("UNDER_MANAGER_REVIEW", "MANAGER"),
        ("UNDER_COLLEGE_REVIEW", "COLLEGE"),
        ("UNDER_HR_REVIEW", "HR"),
        ("UNDER_BUDGET_REVIEW", "BUDGET"),
    ]

    @staticmethod
    def _lock_request(request_obj):
        from hr10_development.models.training_request import HrTrainingRequest

        return (
            HrTrainingRequest.objects.select_for_update()
            .filter(id=request_obj.id, tenant_id=request_obj.tenant_id)
            .first()
        )

    @staticmethod
    def _is_reviewable(status):
        return status == RequestLifecycleStatus.SUBMITTED or status in {
            step[0] for step in ApprovalService.DEFAULT_STEPS
        }

    @staticmethod
    @transaction.atomic
    def approve_step(request_obj, approver_id: int, workflow_version: str,
                     comment: str = "", reason_code: str = "") -> dict:
        """
        推进审批一步。

        Returns: {"approved": bool, "next_status": str}
        """
        request_obj = ApprovalService._lock_request(request_obj)
        if request_obj is None:
            return {"approved": False, "error": DevelopmentErrorCode.NOT_FOUND}

        # 禁止自审批：申请人与审批人相同
        if request_obj.staff_master_id == approver_id:
            return {"approved": False, "error": DevelopmentErrorCode.SELF_APPROVAL_NOT_ALLOWED}

        current_status = request_obj.lifecycle_status
        if not ApprovalService._is_reviewable(current_status):
            return {
                "approved": False,
                "error": DevelopmentErrorCode.REQUEST_ALREADY_FINAL,
            }
        if current_status == RequestLifecycleStatus.SUBMITTED:
            current_status = RequestLifecycleStatus.UNDER_MANAGER_REVIEW
        next_step = ApprovalService._next_step(current_status)

        if next_step is None:
            # 已是最后一步 → APPROVED
            request_obj.lifecycle_status = RequestLifecycleStatus.APPROVED
        else:
            request_obj.lifecycle_status = next_step

        request_obj.current_approval_step += 1
        request_obj.version += 1
        request_obj.save(update_fields=[
            "lifecycle_status", "current_approval_step", "version", "updated_at",
        ])

        # 写不可变审批快照
        HrDevelopmentApprovalSnapshot.objects.create(
            tenant_id=request_obj.tenant_id,
            case_type="HrTrainingRequest",
            case_id=request_obj.id,
            workflow_policy_version_id=workflow_version,
            step_no=request_obj.current_approval_step,
            role=ApprovalService._role_for_status(current_status),
            approver_id=approver_id,
            decision="APPROVED",
            reason_code=reason_code,
            comment=comment,
            object_version=request_obj.version,
            snapshot_hash=ApprovalService._snapshot_hash(request_obj),
            decided_at=datetime.now(timezone.utc),
        )

        return {"approved": True, "next_status": request_obj.lifecycle_status}

    @staticmethod
    @transaction.atomic
    def return_step(request_obj, approver_id: int, workflow_version: str,
                    comment: str = "", reason_code: str = "") -> dict:
        """退回修改（RETURNED 可重提）。"""
        request_obj = ApprovalService._lock_request(request_obj)
        if request_obj is None:
            return {"approved": False, "error": DevelopmentErrorCode.NOT_FOUND}
        current_status = request_obj.lifecycle_status
        if not ApprovalService._is_reviewable(current_status):
            return {
                "approved": False,
                "error": DevelopmentErrorCode.REQUEST_ALREADY_FINAL,
            }
        request_obj.lifecycle_status = RequestLifecycleStatus.RETURNED
        request_obj.version += 1
        request_obj.save(update_fields=["lifecycle_status", "version", "updated_at"])

        HrDevelopmentApprovalSnapshot.objects.create(
            tenant_id=request_obj.tenant_id,
            case_type="HrTrainingRequest",
            case_id=request_obj.id,
            workflow_policy_version_id=workflow_version,
            step_no=request_obj.current_approval_step,
            role=ApprovalService._role_for_status(current_status),
            approver_id=approver_id,
            decision="RETURNED",
            reason_code=reason_code,
            comment=comment,
            object_version=request_obj.version,
            snapshot_hash=ApprovalService._snapshot_hash(request_obj),
            decided_at=datetime.now(timezone.utc),
        )
        return {"approved": False, "next_status": RequestLifecycleStatus.RETURNED}

    @staticmethod
    @transaction.atomic
    def reject(request_obj, approver_id: int, workflow_version: str,
               comment: str = "", reason_code: str = "") -> dict:
        """最终否决（REJECTED 为终局）。"""
        request_obj = ApprovalService._lock_request(request_obj)
        if request_obj is None:
            return {"approved": False, "error": DevelopmentErrorCode.NOT_FOUND}
        current_status = request_obj.lifecycle_status
        if not ApprovalService._is_reviewable(current_status):
            return {
                "approved": False,
                "error": DevelopmentErrorCode.REQUEST_ALREADY_FINAL,
            }
        request_obj.lifecycle_status = RequestLifecycleStatus.REJECTED
        request_obj.version += 1
        request_obj.save(update_fields=["lifecycle_status", "version", "updated_at"])

        HrDevelopmentApprovalSnapshot.objects.create(
            tenant_id=request_obj.tenant_id,
            case_type="HrTrainingRequest",
            case_id=request_obj.id,
            workflow_policy_version_id=workflow_version,
            step_no=request_obj.current_approval_step,
            role=ApprovalService._role_for_status(current_status),
            approver_id=approver_id,
            decision="REJECTED",
            reason_code=reason_code,
            comment=comment,
            object_version=request_obj.version,
            snapshot_hash=ApprovalService._snapshot_hash(request_obj),
            decided_at=datetime.now(timezone.utc),
        )
        return {"approved": False, "next_status": RequestLifecycleStatus.REJECTED}

    @staticmethod
    def _next_step(current_status: str) -> str | None:
        for i, (status, _role) in enumerate(ApprovalService.DEFAULT_STEPS):
            if status == current_status:
                if i + 1 < len(ApprovalService.DEFAULT_STEPS):
                    return ApprovalService.DEFAULT_STEPS[i + 1][0]
                return None
        return None

    @staticmethod
    def _role_for_status(status: str) -> str:
        for s, role in ApprovalService.DEFAULT_STEPS:
            if s == status:
                return role
        return "FINAL"

    @staticmethod
    def _snapshot_hash(obj) -> str:
        raw = json.dumps({
            "id": str(obj.id),
            "lifecycle_status": getattr(obj, "lifecycle_status", ""),
            "current_approval_step": getattr(obj, "current_approval_step", 0),
            "version": getattr(obj, "version", 1),
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()
