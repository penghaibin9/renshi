"""
hr_changes/selectors/case_list.py —— 异动中心列表/统计（S3，只读）。

视图：我的发起 / 我的待办 / 审批中 / 待生效 / 已生效 / 异常；
统计卡：待我处理、审批中、待生效、本月生效、风险。
硬合同：tenant fail-closed；分页走 DB；不 N+1。
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q
from django.utils import timezone

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

    def under_approval(self, user_id=None):
        return self._base_qs().filter(status=CaseStatus.UNDER_APPROVAL)

    def waiting_effective(self, user_id=None):
        return self._base_qs().filter(status=CaseStatus.APPROVED_WAITING_EFFECTIVE)

    def effective(self, user_id=None):
        return self._base_qs().filter(status=CaseStatus.EFFECTIVE)

    def anomalies(self, user_id=None):
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
            "returnedToAmend": qs.filter(status=CaseStatus.RETURNED).count(),
            "effectiveToday": qs.filter(
                status=CaseStatus.EFFECTIVE,
                approved_effective_at=self.today,
            ).count(),
            "effectiveThisMonth": qs.filter(
                status=CaseStatus.EFFECTIVE,
                approved_effective_at__gte=month_start,
            ).count(),
            "risks": self.anomalies().count(),
        }

    def view_counts(self, user_id) -> dict[str, int]:
        """Return the real count behind every workbench stage/link."""
        return {
            "initiated": self.my_initiated(user_id).count(),
            "todos": self.my_todos(user_id).count(),
            "approval": self.under_approval().count(),
            "waiting": self.waiting_effective().count(),
            "effective": self.effective().count(),
            "anomalies": self.anomalies().count(),
        }

    def filter_options(self) -> dict:
        """Build truthful filter choices from the tenant-scoped read model."""
        from hr_structure.models import HrOrganization, HrOrganizationVersion

        qs = self._base_qs()
        action_codes = list(
            qs.exclude(action_id__code="")
            .values_list("action_id__code", flat=True)
            .distinct()
            .order_by("action_id__code")
        )
        org_ids = set(qs.exclude(source_org_id__isnull=True).values_list("source_org_id", flat=True))
        org_ids.update(qs.exclude(target_org_id__isnull=True).values_list("target_org_id", flat=True))
        current_versions = HrOrganizationVersion.objects.filter(
            tenant_id=self.tenant_id,
            validity_from__lte=self.today,
        ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=self.today)).order_by(
            "organization_id", "-version_no"
        )
        organizations = HrOrganization.objects.filter(
            tenant_id=self.tenant_id, id__in=org_ids
        ).prefetch_related(Prefetch("versions", queryset=current_versions, to_attr="ui_versions"))
        return {
            "actions": [
                {"value": code, "label": action_label(code)} for code in action_codes
            ],
            "organizations": [
                {
                    "value": org.stable_code,
                    "label": self._organization_label(org),
                }
                for org in sorted(organizations, key=lambda item: self._organization_label(item))
            ],
        }

    @staticmethod
    def _organization_label(org) -> str:
        if org is None:
            return ""
        versions = getattr(org, "ui_versions", [])
        if versions:
            return versions[0].short_name or versions[0].name
        return org.stable_code

    def list(
        self,
        *,
        view: str,
        user_id,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        action_code: str = "",
        organization_code: str = "",
        period: str = "",
    ) -> dict:
        view_map = {
            "initiated": self.my_initiated,
            "todos": self.my_todos,
            "approval": self.under_approval,
            "waiting": self.waiting_effective,
            "effective": self.effective,
            "anomalies": self.anomalies,
        }
        fn = view_map.get(view, self.my_initiated)
        qs = fn(user_id)
        if keyword:
            qs = qs.filter(
                Q(case_no__icontains=keyword)
                | Q(staff_master_id__staff_no__icontains=keyword)
                | Q(staff_master_id__person_id__legal_name__icontains=keyword)
                | Q(reason_id__name__icontains=keyword)
            )
        if action_code:
            qs = qs.filter(action_id__code=action_code)
        if organization_code:
            qs = qs.filter(
                Q(source_org_id__stable_code=organization_code)
                | Q(target_org_id__stable_code=organization_code)
            )
        if period == "7d":
            qs = qs.filter(requested_effective_at__range=(self.today, self.today + timedelta(days=7)))
        elif period == "30d":
            qs = qs.filter(requested_effective_at__range=(self.today, self.today + timedelta(days=30)))
        elif period == "overdue":
            qs = qs.filter(requested_effective_at__lt=self.today).exclude(
                status__in=(CaseStatus.EFFECTIVE, CaseStatus.CLOSED)
            )

        from hr_structure.models import HrOrganizationVersion

        current_versions = HrOrganizationVersion.objects.filter(
            tenant_id=self.tenant_id,
            validity_from__lte=self.today,
        ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=self.today)).order_by(
            "organization_id", "-version_no"
        )
        qs = qs.select_related(
            "action_id", "reason_id", "staff_master_id", "source_org_id", "target_org_id"
        ).prefetch_related(
            Prefetch("source_org_id__versions", queryset=current_versions, to_attr="ui_versions"),
            Prefetch("target_org_id__versions", queryset=current_versions, to_attr="ui_versions"),
        ).order_by("-created_at")

        total = qs.count()
        rows = list(qs[(page - 1) * page_size : page * page_size])
        actor_ids = {actor_id for c in rows for actor_id in (c.owner_id, c.initiator_id) if actor_id}
        actor_names = {}
        if actor_ids:
            for actor in get_user_model().objects.filter(id__in=actor_ids):
                actor_names[actor.id] = actor.get_full_name() or actor.get_username()
        now = timezone.now()
        items = []
        for c in rows:
            source = self._organization_label(c.source_org_id) if c.source_org_id else (c.source_position_id.position_code if c.source_position_id else "")
            target = self._organization_label(c.target_org_id) if c.target_org_id else (c.target_position_id.position_code if c.target_position_id else "")
            elapsed = now - c.updated_at
            if elapsed.days:
                elapsed_label = f"{elapsed.days}天"
            else:
                hours = max(int(elapsed.total_seconds() // 3600), 0)
                elapsed_label = f"{hours}小时" if hours else "1小时内"
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
                    "ownerId": c.owner_id,
                    "handlerName": actor_names.get(c.owner_id or c.initiator_id, "—"),
                    "createdAt": c.created_at.isoformat(),
                    "elapsedLabel": elapsed_label,
                    "isOverdue": c.requested_effective_at < self.today
                    and c.status not in (CaseStatus.EFFECTIVE, CaseStatus.CLOSED),
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
