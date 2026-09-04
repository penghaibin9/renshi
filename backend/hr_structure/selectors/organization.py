"""
hr_structure/selectors/organization.py

OrganizationSelector —— 组织查询（只读，tenant/scope first，asOf explicit）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from hr_structure.models import HrOrganization, HrOrganizationVersion
from hr_structure.scope import Hr02Scope, organization_ids_for_scope
from hr_structure.selectors.effective import FORMAL_STATUSES, org_version_as_of, children_as_of


class OrganizationSelector:
    def __init__(self, scope: Hr02Scope, as_of: Optional[date] = None):
        self.scope = scope
        self.as_of = as_of or timezone.localdate()

    def _base_qs(self):
        qs = HrOrganization.objects.filter(tenant_id=self.scope.tenant_id)
        allowed = self._allowed_org_ids()
        return qs if allowed is None else qs.filter(id__in=allowed)

    def _allowed_org_ids(self):
        if not hasattr(self, "_scope_org_ids"):
            self._scope_org_ids = organization_ids_for_scope(self.scope, self.as_of)
        return self._scope_org_ids

    def get_root(self) -> Optional[HrOrganizationVersion]:
        """每 tenant 恰好一个当前 SCHOOL 根组织（INV-02）。"""
        versions = (
            HrOrganizationVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                status__in=FORMAL_STATUSES,
                validity_from__lte=self.as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=self.as_of))
        )
        allowed = self._allowed_org_ids()
        if allowed is None:
            versions = versions.filter(org_type="SCHOOL")
        else:
            versions = versions.filter(organization_id=self.scope.org_id)
        return versions.order_by("validity_from", "-version_no").first()

    def get_organization(self, org_id) -> Optional[HrOrganization]:
        """按 tenant 过滤取组织（禁止裸 get）。"""
        return self._base_qs().filter(id=org_id).first()

    def get_version_as_of(self, org_id) -> Optional[HrOrganizationVersion]:
        allowed = self._allowed_org_ids()
        if allowed is not None and int(org_id) not in allowed:
            return None
        return org_version_as_of(self.scope.tenant_id, org_id, self.as_of)

    def get_children(self, org_id):
        allowed = self._allowed_org_ids()
        children = children_as_of(self.scope.tenant_id, org_id, self.as_of)
        return children if allowed is None else children.filter(organization_id__in=allowed)

    def search(self, keyword: str, limit: int = 20):
        """搜索（自动补全/定位）。同 scope；不泄露其他学校。"""
        versions = HrOrganizationVersion.objects.filter(
            tenant_id=self.scope.tenant_id,
            status__in=FORMAL_STATUSES,
            validity_from__lte=self.as_of,
        ).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=self.as_of)
        )
        allowed = self._allowed_org_ids()
        if allowed is not None:
            versions = versions.filter(organization_id__in=allowed)
        if keyword:
            versions = versions.filter(
                Q(name__icontains=keyword)
                | Q(organization_id__stable_code__icontains=keyword)
            )
        return versions.select_related("organization_id").order_by("name")[:limit]

    def get_versions(self, org_id):
        allowed = self._allowed_org_ids()
        versions = HrOrganizationVersion.objects.filter(
            organization_id=org_id,
            tenant_id=self.scope.tenant_id,
        )
        if allowed is not None and int(org_id) not in allowed:
            return versions.none()
        return versions.order_by("validity_from")
