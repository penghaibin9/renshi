"""
hr_external/services/task_service.py —— 教学与服务任务（S7，总册 §44-53）。

- 任务状态机：DRAFT→ASSIGNED→ACCEPTED→IN_PROGRESS→SUBMITTED→UNDER_REVIEW→COMPLETED
  / REJECTED_FOR_CORRECTION / CANCELLED（§47）；
- Task Acceptance：ACCEPT/REQUEST_CLARIFICATION/DECLINE_WITH_REASON（§56，拒绝不删除任务）；
- 工作量：source 四类；本人提交不自动成为正式数量（§52），学院验证后进结算依据（§53）；
- SettlementBasis：HR08 只输出 verified workload + eligible_items（HR15 算金额，§138.9）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction

from hr_external.constants import (
    ExternalTaskStatus,
    SettlementStatus,
    TaskAcceptance,
    WorkloadSource,
    WorkloadVerificationStatus,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalServiceTask,
    HrExternalSettlementBasis,
    HrExternalTaskEvidence,
    HrExternalWorkloadRecord,
)


class TaskOutsideEngagement(Exception):
    code = "EXTERNAL_TASK_OUTSIDE_ENGAGEMENT"


class TaskAlreadyFinalized(Exception):
    code = "EXTERNAL_TASK_ALREADY_FINALIZED"


class WorkloadOverCap(Exception):
    code = "EXTERNAL_WORKLOAD_OVER_CAP"


class TaskStateConflict(Exception):
    code = "VERSION_CONFLICT"


_TASK_TRANSITIONS = {
    ExternalTaskStatus.DRAFT: {ExternalTaskStatus.ASSIGNED, ExternalTaskStatus.CANCELLED},
    ExternalTaskStatus.ASSIGNED: {
        ExternalTaskStatus.ACCEPTED,
        ExternalTaskStatus.IN_PROGRESS,
        ExternalTaskStatus.CANCELLED,
    },
    ExternalTaskStatus.ACCEPTED: {
        ExternalTaskStatus.IN_PROGRESS,
        ExternalTaskStatus.CANCELLED,
    },
    ExternalTaskStatus.IN_PROGRESS: {
        ExternalTaskStatus.SUBMITTED,
        ExternalTaskStatus.CANCELLED,
    },
    ExternalTaskStatus.SUBMITTED: {
        ExternalTaskStatus.UNDER_REVIEW,
        ExternalTaskStatus.REJECTED_FOR_CORRECTION,
    },
    ExternalTaskStatus.UNDER_REVIEW: {
        ExternalTaskStatus.COMPLETED,
        ExternalTaskStatus.REJECTED_FOR_CORRECTION,
    },
    ExternalTaskStatus.REJECTED_FOR_CORRECTION: {
        ExternalTaskStatus.IN_PROGRESS,
        ExternalTaskStatus.CANCELLED,
    },
    ExternalTaskStatus.COMPLETED: set(),
    ExternalTaskStatus.CANCELLED: set(),
}


class TaskService:
    @staticmethod
    def validate_transition(current: str, target: str) -> bool:
        return target in _TASK_TRANSITIONS.get(current, set())

    def _transition(self, task: HrExternalServiceTask, target: str):
        if not self.validate_transition(task.status, target):
            raise TaskStateConflict(f"illegal task transition {task.status} -> {target}")
        task.status = target
        task.save(update_fields=["status", "updated_at"])

    @transaction.atomic
    def create_task(
        self,
        *,
        tenant_id: int,
        engagement_id,
        assignment_id=None,
        task_type: str,
        title: str,
        planned_start: date,
        planned_end: Optional[date] = None,
        source_domain: str = "HR08",
        source_object_type: str = "",
        source_object_id: str = "",
        description: str = "",
        planned_quantity: Optional[float] = None,
        planned_unit: str = "",
        owner_org_id: int,
        reviewer_id=None,
        settlement_eligible: bool = False,
    ) -> HrExternalServiceTask:
        eng = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise TaskOutsideEngagement("engagement not found in tenant")
        # 任务必须落在 Engagement 聘期内（§118/§134）
        if planned_start < eng.start_at or (eng.end_at and planned_start >= eng.end_at):
            raise TaskOutsideEngagement("task outside engagement period")

        return HrExternalServiceTask.objects.create(
            tenant_id=tenant_id,
            engagement_id=eng,
            assignment_id_id=assignment_id,
            task_type=task_type,
            source_domain=source_domain,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            title=title,
            description=description,
            planned_quantity=planned_quantity,
            planned_unit=planned_unit,
            planned_start=planned_start,
            planned_end=planned_end,
            owner_org_id=owner_org_id,
            reviewer_id=reviewer_id,
            settlement_eligible=settlement_eligible,
            status=ExternalTaskStatus.DRAFT,
        )

    def assign(self, task: HrExternalServiceTask):
        self._transition(task, ExternalTaskStatus.ASSIGNED)

    def accept(self, task: HrExternalServiceTask, action: str, reason: str = ""):
        """Task Acceptance（§56）。拒绝不删除任务。"""
        if action == TaskAcceptance.ACCEPTED:
            task.acceptance = TaskAcceptance.ACCEPTED
            self._transition(task, ExternalTaskStatus.ACCEPTED)
        elif action == TaskAcceptance.REQUEST_CLARIFICATION:
            task.acceptance = TaskAcceptance.REQUEST_CLARIFICATION
            task.save(update_fields=["acceptance", "updated_at"])
        elif action == TaskAcceptance.DECLINED_WITH_REASON:
            task.acceptance = TaskAcceptance.DECLINED_WITH_REASON
            task.save(update_fields=["acceptance", "updated_at"])

    def start(self, task: HrExternalServiceTask):
        if task.status == ExternalTaskStatus.ASSIGNED:
            self._transition(task, ExternalTaskStatus.IN_PROGRESS)

    def submit(self, task: HrExternalServiceTask):
        self._transition(task, ExternalTaskStatus.SUBMITTED)

    def review(self, task: HrExternalServiceTask):
        self._transition(task, ExternalTaskStatus.UNDER_REVIEW)

    def complete(self, task: HrExternalServiceTask):
        self._transition(task, ExternalTaskStatus.COMPLETED)

    def reject_for_correction(self, task: HrExternalServiceTask):
        self._transition(task, ExternalTaskStatus.REJECTED_FOR_CORRECTION)

    def add_evidence(
        self,
        *,
        tenant_id: int,
        task_id,
        evidence_type: str,
        document_id: str = "",
        submitted_by=None,
    ) -> HrExternalTaskEvidence:
        task = HrExternalServiceTask.objects.filter(
            tenant_id=tenant_id, id=task_id
        ).first()
        if task is None:
            raise TaskOutsideEngagement("EXTERNAL_TASK_NOT_FOUND")
        if task.status == ExternalTaskStatus.COMPLETED:
            raise TaskAlreadyFinalized("task already completed")
        return HrExternalTaskEvidence.objects.create(
            tenant_id=tenant_id,
            task_id=task,
            evidence_type=evidence_type,
            document_id=document_id,
            submitted_by=submitted_by,
            status="UPLOADED",
        )

    @transaction.atomic
    def add_workload(
        self,
        *,
        tenant_id: int,
        engagement_id,
        task_id=None,
        source: str = WorkloadSource.SYSTEM_CALCULATED,
        quantity: float,
        unit: str = "",
        service_date: date,
        verified: bool = False,
    ) -> HrExternalWorkloadRecord:
        eng = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise TaskOutsideEngagement("engagement not found in tenant")

        # 工作量 cap 校验（§35/§121）
        if eng.workload_cap is not None:
            total = sum(
                (r.quantity for r in eng.workload_records.all() if r.verification_status == "VERIFIED"),
                0,
            )
            if total + quantity > eng.workload_cap:
                raise WorkloadOverCap("workload exceeds engagement cap")

        record = HrExternalWorkloadRecord.objects.create(
            tenant_id=tenant_id,
            engagement_id=eng,
            task_id_id=task_id,
            source=source,
            quantity=quantity,
            unit=unit,
            service_date=service_date,
            verification_status=(
                WorkloadVerificationStatus.VERIFIED
                if verified
                else WorkloadVerificationStatus.UNVERIFIED
            ),
            settlement_status=(
                SettlementStatus.PENDING if verified else SettlementStatus.NOT_ELIGIBLE
            ),
        )
        return record

    def verify_workload(self, record: HrExternalWorkloadRecord, *, verified: bool, by=None):
        """学院验证（§52）。VERIFIED 后不可原地改。"""
        if record.verification_status == WorkloadVerificationStatus.VERIFIED:
            raise TaskAlreadyFinalized("workload already verified")
        record.verification_status = (
            WorkloadVerificationStatus.VERIFIED if verified else WorkloadVerificationStatus.REJECTED
        )
        record.settlement_status = SettlementStatus.PENDING if verified else SettlementStatus.NOT_ELIGIBLE
        record.verified_by = by
        from django.utils import timezone

        record.verified_at = timezone.now() if verified else None
        record.save(
            update_fields=[
                "verification_status",
                "settlement_status",
                "verified_by",
                "verified_at",
                "updated_at",
            ]
        )

    @transaction.atomic
    def build_settlement_basis(
        self,
        *,
        tenant_id: int,
        engagement_id,
        period: str,
        policy_ref: str = "",
    ) -> HrExternalSettlementBasis:
        """聚合 verified workload → SettlementBasis（§53/§100）。"""
        eng = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise TaskOutsideEngagement("engagement not found in tenant")

        verified = eng.workload_records.filter(verification_status="VERIFIED")
        total = sum((r.quantity for r in verified), 0)
        items = [
            {
                "taskId": str(r.task_id_id) if r.task_id_id else None,
                "quantity": float(r.quantity),
                "unit": r.unit,
                "source": r.source,
            }
            for r in verified
        ]
        basis, created = HrExternalSettlementBasis.objects.get_or_create(
            tenant_id=tenant_id,
            engagement_id=eng,
            period=period,
            defaults={
                "verified_workload": total,
                "eligible_items": items,
                "policy_ref": policy_ref,
                "status": SettlementStatus.READY,
            },
        )
        if not created:
            basis.verified_workload = total
            basis.eligible_items = items
            basis.policy_ref = policy_ref or basis.policy_ref
            basis.status = SettlementStatus.READY
            basis.save(update_fields=["verified_workload", "eligible_items", "policy_ref", "status", "updated_at"])
        return basis
