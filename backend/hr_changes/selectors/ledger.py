"""
hr_changes/selectors/ledger.py —— 异动台账（S7，总册 §31/§32，只读）。

台账列表 + 筛选（年度/组织/动作/原因/状态/生效区间/人员）+ as-of 与 HR03 facts 可互相验证。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from hr_changes.api.labels import action_label, case_status_label
from hr_changes.models import HrPersonnelChangeCase


class LedgerSelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def list(
        self,
        *,
        year: Optional[int] = None,
        org_id: Optional[int] = None,
        action_code: Optional[str] = None,
        reason_code: Optional[str] = None,
        status: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        staff_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        qs = HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id)
        if year:
            qs = qs.filter(requested_effective_at__year=year)
        if org_id:
            qs = qs.filter(target_org_id=org_id)
        if action_code:
            qs = qs.filter(action_id__code=action_code)
        if reason_code:
            qs = qs.filter(reason_id__code=reason_code)
        if status:
            qs = qs.filter(status=status)
        if effective_from:
            qs = qs.filter(requested_effective_at__gte=effective_from)
        if effective_to:
            qs = qs.filter(requested_effective_at__lte=effective_to)
        if staff_id:
            qs = qs.filter(staff_master_id=staff_id)

        qs = (
            qs.select_related(
                "action_id", "reason_id", "staff_master_id",
                "source_org_id", "target_org_id", "source_position_id", "target_position_id",
            )
            .order_by("-requested_effective_at", "-created_at")
        )
        total = qs.count()
        rows = list(qs[(page - 1) * page_size : page * page_size])
        items = []
        for c in rows:
            items.append(
                {
                    "id": str(c.id),
                    "caseNo": c.case_no,
                    "staffId": str(c.staff_master_id_id),
                    "staffName": c.staff_master_id.person_id.legal_name,
                    "staffNo": c.staff_master_id.staff_no,
                    "actionCode": c.action_id.code,
                    "actionLabel": action_label(c.action_id.code),
                    "reasonCode": c.reason_id.code,
                    "reasonName": c.reason_id.name,
                    "sourceOrg": c.source_org_id.stable_code if c.source_org_id else (
                        c.source_position_id.position_code if c.source_position_id else ""
                    ),
                    "targetOrg": c.target_org_id.stable_code if c.target_org_id else (
                        c.target_position_id.position_code if c.target_position_id else ""
                    ),
                    "requestedEffectiveAt": c.requested_effective_at.isoformat(),
                    "approvedAt": c.approved_at.isoformat() if c.approved_at else None,
                    "appliedAt": c.applied_at.isoformat() if c.applied_at else None,
                    "status": c.status,
                    "statusLabel": case_status_label(c.status),
                    "initiatorId": c.initiator_id,
                }
            )
        return {"items": items, "total": total, "page": page, "pageSize": page_size}

    def staff_history(self, staff_id: str) -> dict:
        """人员异动历史（/hr/staff/:staffId/change-history）。"""
        cases = (
            HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id, staff_master_id=staff_id)
            .select_related("action_id", "reason_id", "target_org_id")
            .order_by("-requested_effective_at")
        )
        return {
            "staffId": staff_id,
            "items": [
                {
                    "id": str(c.id),
                    "caseNo": c.case_no,
                    "actionCode": c.action_id.code,
                    "actionLabel": action_label(c.action_id.code),
                    "reasonName": c.reason_id.name,
                    "target": c.target_org_id.stable_code if c.target_org_id else "",
                    "requestedEffectiveAt": c.requested_effective_at.isoformat(),
                    "status": c.status,
                    "statusLabel": case_status_label(c.status),
                }
                for c in cases
            ],
        }
