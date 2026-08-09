"""
hr_changes/selectors/case_list.py —— 异动中心列表/统计（S3，只读）。

视图：我的发起 / 我的待办 / 审批中 / 待生效 / 已生效 / 异常；
统计卡：待我处理、审批中、待生效、本月生效、风险。
硬合同：tenant fail-closed；分页走 DB；不 N+1。
"""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Q

from hr_changes.api.labels import action_label, case_status_label
from hr_changes.constants import CaseStatus
from hr_changes.context import HrChangeRequestContext
from hr_changes.models import HrPersonnelChangeCase


class CaseListSelector:
    def __init__(self, context: HrChangeRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id
        self.today = context.today()

    def _base_qs(self):
        return HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id)

    def my_initiated(self, user_id):
        return self._base_qs().filter(initiator_id=user_id)

    def my_todos(self, user_id):
        """待我处理：审批中且当前步骤待我处理（V1 简化：审批中案件按学校/组织 scope 匹配）。"""
        from hr_changes.services.approval_service import ApprovalService

        return self._base_qs().filter(status=CaseStatus.UNDER_APPROVAL)

    def under_approval(self):
        return self._base_qs().filter(status=CaseStatus.UNDER_APPROVAL)

    def waiting_effective(self):
        return self._base_qs().filter(status=CaseStatus.APPROVED_WAITING_EFFECTIVE)

    def effective(self):
        return self._base_qs().filter(status=CaseStatus.EFFECTIVE)

    def anomalies(self):
        return self._base_qs().filter(
            status__in=(CaseStatus.APPLY_FAILED, CaseStatus.REJECTED, CaseStatus.CANCELLED)
        )

    # ------------------------------------------------------------------
    def stats(self, user_id) -> dict:
        qs = self._base_qs()
        month_start = self.today.replace(day=1)
        return {
            "myTodos": self.my_todos(user_id).count(),
            "underApproval": self.under_approval().count(),
            "waitingEffective": self.waiting_effective().count(),
            "effectiveThisMonth": qs.filter(
                status=CaseStatus.EFFECTIVE,
                approved_effective_at__gte=month_start,
            ).count(),
            "risks": self.anomalies().count(),
        }

    def list(self, *, view: str, user_id, page: int = 1, page_size: int = 20) -> dict:
        view_map = {
            "initiated": self.my_initiated,
            "todos": self.my_todos,
            "approval": self.under_approval,
            "waiting": self.waiting_effective,
            "effective": self.effective,
            "anomalies": self.anomalies,
        }
        fn = view_map.get(view, self.my_initiated)
        qs = fn(user_id).select_related(
            "action_id", "reason_id", "staff_master_id", "source_org_id", "target_org_id"
        ).order_by("-created_at")

        total = qs.count()
        rows = list(qs[(page - 1) * page_size : page * page_size])
        items = []
        for c in rows:
            source = c.source_org_id.stable_code if c.source_org_id else (c.source_position_id.position_code if c.source_position_id else "")
            target = c.target_org_id.stable_code if c.target_org_id else (c.target_position_id.position_code if c.target_position_id else "")
            items.append(
                {
                    "id": str(c.id),
                    "caseNo": c.case_no,
                    "staffName": c.staff_master_id.person_id.legal_name,
                    "staffNo": c.staff_master_id.staff_no,
                    "actionCode": c.action_id.code,
                    "actionLabel": action_label(c.action_id.code),
                    "reasonCode": c.reason_id.code,
                    "reasonName": c.reason_id.name,
                    "source": source,
                    "target": target,
                    "requestedEffectiveAt": c.requested_effective_at.isoformat(),
                    "status": c.status,
                    "statusLabel": case_status_label(c.status),
                    "priority": c.priority,
                    "initiatorId": c.initiator_id,
                    "createdAt": c.created_at.isoformat(),
                    "version": c.version,
                }
            )
        return {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "hasNext": page * page_size < total,
        }
