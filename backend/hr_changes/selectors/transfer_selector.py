"""
hr_changes/selectors/transfer_selector.py —— 校内调动列表/详情（S4，只读）。

列表：transfer 动作案件；详情：Before/After 对照（current_vs_target）。
"""

from __future__ import annotations

from hr_changes.api.labels import action_label, case_status_label
from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.services.transfer_service import TransferService

TRANSFER_ACTIONS = (
    ChangeActionCode.ORG_TRANSFER,
    ChangeActionCode.POSITION_TRANSFER,
    ChangeActionCode.ORG_POSITION_TRANSFER,
)


class TransferSelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def list(self, *, page: int = 1, page_size: int = 20) -> dict:
        qs = (
            HrPersonnelChangeCase.objects.filter(
                tenant_id=self.tenant_id,
                action_id__code__in=TRANSFER_ACTIONS,
            )
            .select_related("action_id", "staff_master_id", "source_org_id", "target_org_id")
            .order_by("-created_at")
        )
        total = qs.count()
        rows = list(qs[(page - 1) * page_size : page * page_size])
        items = []
        for c in rows:
            items.append(
                {
                    "id": str(c.id),
                    "caseNo": c.case_no,
                    "staffName": c.staff_master_id.person_id.legal_name,
                    "staffNo": c.staff_master_id.staff_no,
                    "actionCode": c.action_id.code,
                    "actionLabel": action_label(c.action_id.code),
                    "source": c.source_org_id.stable_code if c.source_org_id else "",
                    "target": c.target_org_id.stable_code if c.target_org_id else "",
                    "requestedEffectiveAt": c.requested_effective_at.isoformat(),
                    "status": c.status,
                    "statusLabel": case_status_label(c.status),
                }
            )
        return {"items": items, "total": total, "page": page, "pageSize": page_size}

    def detail(self, case_id) -> dict | None:
        case = (
            HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id, id=case_id)
            .select_related("action_id", "staff_master_id", "source_org_id", "target_org_id")
            .first()
        )
        if case is None:
            return None
        from hr_changes.selectors.case_detail import CaseDetailSelector

        base = CaseDetailSelector(self.tenant_id).get(case.id)
        base["beforeAfter"] = TransferService(self.tenant_id).current_vs_target(case)
        return base
