"""
hr_changes/selectors/temporary_selector.py —— 借调挂职列表/统计（S6，只读）。

统计卡：借调挂职中 / 30 天内返岗 / 已超期 / 待返岗确认。
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from hr_changes.api.labels import action_label, source_assignment_policy_label
from hr_changes.models import HrTemporaryAssignmentLink


class TemporarySelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def stats(self, as_of: date | None = None) -> dict:
        as_of = as_of or timezone.localdate()
        horizon = as_of + timedelta(days=30)
        qs = HrTemporaryAssignmentLink.objects.filter(tenant_id=self.tenant_id)
        return {
            "active": qs.filter(status__in=("ACTIVE", "EXTENDED")).count(),
            "dueSoon": qs.filter(
                status__in=("ACTIVE", "EXTENDED"),
                expected_return_at__lte=horizon,
                expected_return_at__gt=as_of,
            ).count(),
            "overdue": qs.filter(
                status__in=("ACTIVE", "EXTENDED"),
                expected_return_at__lt=as_of,
            ).count(),
            "returnPending": qs.filter(status="RETURNING").count(),
        }

    def list(self, *, status: str = "", as_of: date | None = None) -> dict:
        as_of = as_of or timezone.localdate()
        qs = (
            HrTemporaryAssignmentLink.objects.filter(tenant_id=self.tenant_id)
            .select_related(
                "change_case_id",
                "change_case_id__staff_master_id",
                "change_case_id__action_id",
                "source_assignment_id__organization_id",
                "temporary_assignment_id__organization_id",
            )
            .order_by("-start_at")
        )
        if status in ("ACTIVE", "EXTENDED", "RETURNED", "OVERDUE", "RETURN_TARGET_INVALID", "CANCELLED"):
            qs = qs.filter(status=status)

        items = []
        for link in qs:
            staff = link.change_case_id.staff_master_id
            overdue = (
                link.status in ("ACTIVE", "EXTENDED")
                and link.expected_return_at < as_of
            )
            items.append(
                {
                    "id": str(link.id),
                    "caseId": str(link.change_case_id_id),
                    "caseNo": link.change_case_id.case_no,
                    "staffName": staff.person_id.legal_name,
                    "staffNo": staff.staff_no,
                    "actionCode": link.change_case_id.action_id.code,
                    "actionLabel": action_label(link.change_case_id.action_id.code),
                    "sourceOrg": (
                        link.source_assignment_id.organization_id.stable_code
                        if link.source_assignment_id.organization_id else ""
                    ),
                    "tempOrg": (
                        link.temporary_assignment_id.organization_id.stable_code
                        if link.temporary_assignment_id.organization_id else ""
                    ),
                    "startAt": link.start_at.isoformat(),
                    "expectedReturnAt": link.expected_return_at.isoformat(),
                    "sourcePolicy": link.source_assignment_status_policy,
                    "sourcePolicyLabel": source_assignment_policy_label(
                        link.source_assignment_status_policy
                    ),
                    "status": "OVERDUE" if overdue else link.status,
                }
            )
        return {"items": items, "stats": self.stats(as_of)}
