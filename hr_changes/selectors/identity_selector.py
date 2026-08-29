"""HR06 岗位与身份变更列表读模型。"""

from hr_changes.api.labels import action_label, case_status_label
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.policies.identity_policy import IDENTITY_FIELD_MAP


IDENTITY_ACTIONS = tuple(IDENTITY_FIELD_MAP.keys())


class IdentitySelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def list(self) -> dict:
        cases = (
            HrPersonnelChangeCase.objects.filter(
                tenant_id=self.tenant_id,
                action_id__code__in=IDENTITY_ACTIONS,
            )
            .select_related(
                "action_id",
                "staff_master_id",
                "staff_master_id__person_id",
                "target_org_id",
            )
            .order_by("-created_at")
        )
        items = [
            {
                "id": str(case.id),
                "caseNo": case.case_no,
                "staffName": case.staff_master_id.person_id.legal_name,
                "staffNo": case.staff_master_id.staff_no,
                "actionCode": case.action_id.code,
                "actionLabel": action_label(case.action_id.code),
                "target": case.target_org_id.stable_code if case.target_org_id else "",
                "requestedEffectiveAt": case.requested_effective_at.isoformat(),
                "status": case.status,
                "statusLabel": case_status_label(case.status),
            }
            for case in cases
        ]
        return {"items": items, "total": len(items)}
