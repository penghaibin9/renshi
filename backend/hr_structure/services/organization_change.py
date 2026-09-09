"""
hr_structure/services/organization_change.py

OrganizationChangeService —— 组织新建/变更（总册 9.6 / 14 节）。

校验链：tenant → scope → cycle → effective overlap → impact → audit → create case/version。
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from horilla.hr_event_service import emit_registered_event

from hr_structure.authority_registry import EVENT_ORGANIZATION_CREATED
from hr_structure.models import (
    HrOrganization,
    HrOrganizationVersion,
    HrStructureChangeCase,
)
from hr_structure.scope import Hr02Scope, lock_materialized_school


class Hr02ServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _detect_cycle(tenant_id, parent_id, candidate_child_id) -> bool:
    """检测把 candidate_child_id 挂到 parent_id 下是否成环（INV-03）。"""
    if parent_id is None:
        return False
    current = parent_id
    seen = set()
    # 向上回溯：如果 candidate 已经是 parent 的祖先，则成环
    while current:
        if current == candidate_child_id:
            return True
        if current in seen:
            return True
        seen.add(current)
        parent = (
            HrOrganizationVersion.objects.filter(
                organization_id=current,
                tenant_id=tenant_id,
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            )
            .filter(validity_to__isnull=True)
            .values_list("parent_organization_id", flat=True)
            .first()
        )
        current = parent
    return False


class OrganizationChangeService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    @transaction.atomic
    def create_organization(
        self,
        *,
        stable_code: str,
        name: str,
        org_type: str,
        dimension: str,
        parent_id=None,
        validity_from: date,
        sort_order: int = 0,
        short_name: str = "",
    ) -> HrOrganization:
        """新建组织（CREATE_ORG）。"""
        lock_materialized_school(self.scope.tenant_id)
        if validity_from < timezone.localdate():
            raise Hr02ServiceError("HR02_EFFECTIVE_RANGE_OVERLAP", "生效日期不能早于今天")
        # parent 必须属于本 tenant（INV-01），否则跨租户引用
        if parent_id:
            from hr_structure.models import HrOrganization as _Org

            parent = _Org.objects.filter(tenant_id=self.scope.tenant_id, id=parent_id).first()
            if parent is None:
                raise Hr02ServiceError("HR02_CROSS_TENANT_REFERENCE", "上级组织不存在或跨租户")
        # SCHOOL 根唯一性（INV-02）：每 tenant 恰好一个 SCHOOL 根
        if org_type == "SCHOOL":
            existing_root = HrOrganizationVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                org_type="SCHOOL",
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            ).exists()
            if existing_root:
                raise Hr02ServiceError("HR02_SCOPE_DENIED", "该学校已存在根组织，禁止重复创建")

        org = HrOrganization.objects.create(
            tenant_id=self.scope.tenant_id,
            stable_code=stable_code,
            org_dimension=dimension,
            created_by=self.actor,
        )
        version = HrOrganizationVersion.objects.create(
            organization_id=org,
            tenant_id=self.scope.tenant_id,
            name=name,
            short_name=short_name,
            org_type=org_type,
            parent_organization_id_id=parent_id,
            validity_from=validity_from,
            status=HrOrganizationVersion.Status.EFFECTIVE,
            sort_order=sort_order,
            created_by=self.actor,
        )
        # 主树 parent 一致性：version.parent 与 relation(ADMIN_PARENT) 同步维护
        # （总册 8.2 + 10.3：同组织同 dimension 同日期最多一个 primary parent）
        if parent_id and dimension == "ADMIN":
            from hr_structure.models import HrOrganizationRelation

            HrOrganizationRelation.objects.create(
                tenant_id=self.scope.tenant_id,
                source_org_id_id=org.id,
                target_org_id_id=parent_id,
                relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                validity_from=validity_from,
                status=HrOrganizationRelation.Status.ACTIVE,
                created_by=self.actor,
            )
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_ORGANIZATION_CREATED,
            payload={
                "organizationId": str(org.id),
                "stableCode": org.stable_code,
                "versionId": str(version.id),
                "effectiveDate": validity_from.isoformat(),
            },
        )
        return org

    @transaction.atomic
    def create_change_case(
        self,
        *,
        change_type: str,
        title: str,
        reason: str,
        requested_effective_date: date,
        items: list,
    ) -> HrStructureChangeCase:
        """创建变更 case（总册 14.3）。写操作需 Idempotency-Key（调用方保证）。"""
        if requested_effective_date < timezone.localdate():
            raise Hr02ServiceError("HR02_EFFECTIVE_RANGE_OVERLAP", "生效日期不能早于今天")
        case_no = f"CASE-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        case = HrStructureChangeCase.objects.create(
            tenant_id=self.scope.tenant_id,
            case_no=case_no,
            change_type=change_type,
            title=title,
            reason=reason,
            requested_effective_date=requested_effective_date,
            status=HrStructureChangeCase.Status.DRAFT,
            initiator_id=self.actor,
            created_by=self.actor,
        )
        from hr_structure.models import HrStructureChangeItem

        for seq, item in enumerate(items, start=1):
            HrStructureChangeItem.objects.create(
                case_id=case,
                sequence=seq,
                entity_type=item.get("entity_type", ""),
                entity_id=str(item.get("entity_id", "")),
                action_type=item.get("action_type", ""),
                before_snapshot=item.get("before_snapshot", {}),
                after_payload=item.get("after_payload", {}),
            )
        return case
