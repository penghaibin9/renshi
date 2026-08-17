"""
hr_changes/services/bulk_service.py —— 批量异动（S8，总册 §38/§39）。

- 默认 PREVALIDATE_ALL：批量执行前逐项校验；
- 执行策略 ATOMIC_BATCH（整体事务） / ITEMIZED_COMMIT（逐项提交，部分失败可继续）；
- 每人独立产生 Change Case（禁一个批量 SQL UPDATE）；
- 失败项 error_json + error_workbook_json 记录，可重试。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrBulkChangeBatch, HrBulkChangeItem, HrPersonnelChangeCase
from hr_changes.services.apply_service import ApplyService, ApplyServiceError
from hr_changes.services.change_service import ChangeService, ChangeServiceError


class BulkServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class BulkService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    def prevalidate(self, batch: HrBulkChangeBatch) -> dict:
        """PREVALIDATE_ALL：为每 item 创建 case 并校验（不提交审批）。"""
        items = list(batch.items.select_related("staff_master_id").order_by("sequence"))
        results = []
        for item in items:
            item.validation_status = "PENDING"
            item.error_json = {}
            try:
                case = self._create_item_case(batch, item)
                item.change_case_id = case
                item.validation_status = "VALID"
            except (ChangeServiceError, Exception) as exc:  # noqa: BLE001
                item.validation_status = "INVALID"
                item.error_json = {
                    "code": getattr(exc, "code", "CHANGE_BULK_PREVALIDATE_FAILED"),
                    "message": str(exc)[:500],
                }
            item.save(update_fields=["change_case_id", "validation_status", "error_json"])
            results.append(
                {"itemId": str(item.id), "staffNo": item.staff_master_id.staff_no,
                 "status": item.validation_status, "error": item.error_json}
            )
        batch.status = HrBulkChangeBatch.Status.PREVALIDATED
        batch.save(update_fields=["status", "updated_at"])
        return {"results": results}

    def _create_item_case(self, batch: HrBulkChangeBatch, item: HrBulkChangeItem) -> HrPersonnelChangeCase:
        from hr_changes.models import HrChangeReason

        reason = HrChangeReason.objects.filter(
            tenant_id=self.tenant_id,
            action_code=batch.action_id.code,
            active=True,
        ).first()
        if reason is None:
            raise ChangeServiceError("CHANGE_INVALID_REASON", "批量动作缺少原因配置")
        case = ChangeService(self.tenant_id, actor_user_id=self.actor_user_id).create_case(
            staff_master_id=item.staff_master_id,
            action_id=batch.action_id,
            reason_id=reason,
            requested_effective_at=batch.requested_effective_at,
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(batch.target_org_id_id),
                    "proposed_value_display": str(batch.target_org_id_id),
                }
            ]
            if batch.target_org_id_id else [],
            target_org_id=batch.target_org_id,
            target_position_id=batch.target_position_id,
        )
        return case

    # ------------------------------------------------------------------
    def execute(
        self, batch_id, *, approve_first: bool = True,
    ) -> dict:
        """执行批量（每人独立 Case → 审批 → 生效）。"""
        batch = (
            HrBulkChangeBatch.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=batch_id)
            .first()
        )
        if batch is None:
            raise BulkServiceError("CHANGE_NOT_FOUND", "批量任务不存在")
        items = list(batch.items.select_related("change_case_id").order_by("sequence"))
        results = []
        apply_service = ApplyService(self.tenant_id, actor_user_id=self.actor_user_id)
        change_service = ChangeService(self.tenant_id, actor_user_id=self.actor_user_id)

        for item in items:
            case = item.change_case_id
            item.execution_status = "RUNNING"
            item.save(update_fields=["execution_status"])
            try:
                if case is None:
                    raise BulkServiceError("CHANGE_NOT_FOUND", "item 缺少 Case")
                if approve_first:
                    case = change_service.submit(case.id)
                    case = change_service.start_approval(case.id)
                    case = change_service.approve_all(case.id)
                applied = apply_service.apply_case(case.id)
                item.execution_status = (
                    "SUCCESS" if applied.status == "EFFECTIVE" else "FAILED"
                )
                item.error_json = {}
            except (ChangeServiceError, ApplyServiceError, BulkServiceError) as exc:
                item.execution_status = "FAILED"
                item.error_json = {
                    "code": getattr(exc, "code", "CHANGE_BULK_PARTIAL_FAILED"),
                    "message": str(exc)[:500],
                }
            item.save(update_fields=["execution_status", "error_json"])
            results.append(
                {
                    "itemId": str(item.id),
                    "staffNo": item.staff_master_id.staff_no,
                    "executionStatus": item.execution_status,
                    "error": item.error_json,
                }
            )

        failed = sum(1 for r in results if r["executionStatus"] == "FAILED")
        if failed == 0:
            batch.status = HrBulkChangeBatch.Status.COMPLETED
        elif failed == len(results):
            batch.status = HrBulkChangeBatch.Status.FAILED
        else:
            batch.status = HrBulkChangeBatch.Status.PARTIAL_FAILED
        batch.error_workbook_json = {
            "failed": [r for r in results if r["executionStatus"] == "FAILED"]
        }
        batch.save(update_fields=["status", "error_workbook_json", "updated_at"])
        return {"results": results, "batchStatus": batch.status}
