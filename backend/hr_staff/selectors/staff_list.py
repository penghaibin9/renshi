"""
hr_staff/selectors/staff_list.py —— HR03-01 名册查询（只读，S4）。

硬合同（总册 §10 / §35）：
- tenant → scope → permission → 字段策略四层后才有数据；
- 只返回当前 as_of（默认学校时区今天）的当前人事事实，不伪装历史；
- 高敏字段（HIGH_SENSITIVE）默认不进列表 API；RESTRICTED/SENSITIVE 按权限裁剪；
- 服务器端翻译为受控 QuerySpec，不接收任意 ORM field path；
- 任意不完整/未知 scope 都 fail-closed，绝不回退全校；
- select_related/prefetch 预算：名册 50 行 ≤ 10~15 SQL。
"""

from __future__ import annotations

from typing import Optional

from django.db.models import Prefetch, Q

from hr_staff.constants import AssignmentType, StaffScopeType
from hr_staff.context import HrStaffRequestContext
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment, HrStaffMaster
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


STAFF_LIST_FIELDS = frozenset(
    {
        "staff_id",
        "staff_uid",
        "staff_no",
        "legal_name",
        "preferred_name",
        "staff_category_code",
        "current_employment_status",
        "org_id",
        "org_name",
        "position_name",
        "primary_assignment_type",
        "date_joining",
        "relationship_type",
        "has_future_change",
    }
)

DEFAULT_ORG_SCOPE_IDENTIFIERS = ("SCHOOL", "COLLEGE", "DEPARTMENT")


class StaffListQuerySpecError(Exception):
    code = "STAFF_LIST_QUERY_INVALID"


class StaffListSelector:
    """名册读模型（当前事实投影 + 关联 HR02 组织名解析）。"""

    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id
        self.as_of = context.as_of or context.today()

    def base_qs(self):
        return (
            HrStaffMaster.objects.filter(tenant_id=self.tenant_id)
            .select_related("person_id")
            .prefetch_related(
                Prefetch(
                    "employment_relationships",
                    queryset=HrEmploymentRelationship.objects.filter(
                        tenant_id=self.tenant_id
                    ).order_by("effective_from"),
                    to_attr="_rels",
                )
            )
        )

    def _scope_org_ids(self) -> Optional[set]:
        """COLLEGE/DEPARTMENT scope → 允许的组织 id 集合（含子树）。"""
        scope = self.context.scope
        if scope.scope_type not in (StaffScopeType.COLLEGE, StaffScopeType.DEPARTMENT):
            return None
        if scope.org_id is None:
            return set()
        try:
            from hr_structure.selectors.effective import build_tree_as_of

            nodes = build_tree_as_of(
                self.tenant_id, scope.org_id, self.as_of, depth_limit=6
            )
            return {node["id"] for node in nodes} | {scope.org_id}
        except Exception:
            # HR02 子树解析失败时只能缩小到明确请求的组织，不能扩大到 SCHOOL。
            return {scope.org_id}

    def apply_scope(self, qs):
        """严格应用数据范围；缺少 scope 载荷时返回 none，而不是全校。"""
        scope = self.context.scope
        if scope.scope_type == StaffScopeType.SCHOOL:
            return qs
        if scope.scope_type in (
            StaffScopeType.SELF,
            StaffScopeType.EXPLICIT_STAFF_SET,
            StaffScopeType.ASSIGNMENT,
        ):
            if not scope.staff_ids:
                return qs.none()
            return qs.filter(id__in=scope.staff_ids)
        if scope.scope_type in (StaffScopeType.COLLEGE, StaffScopeType.DEPARTMENT):
            org_ids = self._scope_org_ids()
            if not org_ids:
                return qs.none()
            current_primary_staff = (
                HrStaffAssignment.objects.filter(
                    tenant_id=self.tenant_id,
                    assignment_type=AssignmentType.PRIMARY,
                    status="ACTIVE",
                    effective_from__lte=self.as_of,
                    organization_id__in=org_ids,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of))
                .values_list("employment_relationship_id__staff_id", flat=True)
            )
            return qs.filter(id__in=current_primary_staff)
        return qs.none()

    def apply_filters(self, qs, params: dict):
        keyword = (params.get("keyword") or "").strip()
        if keyword:
            qs = qs.filter(
                Q(staff_no__icontains=keyword)
                | Q(person_id__legal_name__icontains=keyword)
                | Q(person_id__preferred_name__icontains=keyword)
            )

        status = (params.get("status") or "").strip()
        if status:
            qs = qs.filter(current_employment_status=status)

        category = (params.get("category") or "").strip()
        if category:
            qs = qs.filter(staff_category_code=category)

        relationship_type = (params.get("relationship_type") or "").strip()
        if relationship_type:
            rel_staff_ids = (
                HrEmploymentRelationship.objects.filter(
                    tenant_id=self.tenant_id,
                    relationship_type=relationship_type,
                    status="ACTIVE",
                    effective_from__lte=self.as_of,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of))
                .values_list("staff_id", flat=True)
            )
            qs = qs.filter(id__in=rel_staff_ids)

        joining_from = params.get("joining_from")
        joining_to = params.get("joining_to")
        if joining_from or joining_to:
            joining_filter = Q()
            if joining_from:
                joining_filter &= Q(employment_relationships__effective_from__gte=joining_from)
            if joining_to:
                joining_filter &= Q(employment_relationships__effective_from__lte=joining_to)
            qs = qs.filter(joining_filter).distinct()

        has_future = params.get("has_future_change")
        if has_future in ("1", "true", "True"):
            future_staff_ids = HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, effective_from__gt=self.as_of
            ).values_list("staff_id", flat=True)
            qs = qs.filter(id__in=future_staff_ids)
        return qs

    def _current_primary(self, staff):
        rel_ids = [
            rel.id for rel in getattr(staff, "_rels", []) if rel.status == "ACTIVE"
        ]
        if not rel_ids:
            return None
        assignments = (
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id__in=rel_ids,
                assignment_type=AssignmentType.PRIMARY,
                status="ACTIVE",
            )
            .filter(effective_from__lte=self.as_of)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of))
            .select_related("organization_id", "position_id", "post_catalog_id")
            .order_by("effective_from")
        )
        return assignments.first()

    def _earliest_joining(self, staff):
        rels = [
            relationship
            for relationship in getattr(staff, "_rels", [])
            if relationship.effective_from is not None
        ]
        return min((relationship.effective_from for relationship in rels), default=None)

    def to_row(self, staff, primary, *, org_name=None, has_future_change=False) -> dict:
        joining = self._earliest_joining(staff)
        return {
            "staff_id": str(staff.id),
            "staff_uid": str(staff.staff_uid),
            "staff_no": staff.staff_no,
            "legal_name": staff.person_id.legal_name,
            "preferred_name": staff.person_id.preferred_name,
            "staff_category_code": staff.staff_category_code,
            "current_employment_status": staff.current_employment_status or "PENDING_ENTRY",
            "org_id": str(primary.organization_id_id)
            if primary and primary.organization_id
            else None,
            "org_name": org_name if org_name is not None else self._org_display(primary),
            "position_name": primary.position_id.position_code
            if primary and primary.position_id
            else None,
            "primary_assignment_type": "PRIMARY",
            "date_joining": joining.isoformat() if joining else None,
            "relationship_type": getattr(staff._rels[0], "relationship_type", None)
            if getattr(staff, "_rels", None)
            else None,
            "has_future_change": has_future_change,
        }

    def _org_display(self, primary):
        if primary is None:
            return None
        if primary.organization_id:
            return EffectiveDatedQueryService(self.tenant_id).org_name_as_of(
                primary.organization_id_id, self.as_of
            ) or primary.organization_id.stable_code
        if primary.legacy_department_id:
            return f"legacy:{primary.legacy_department_id}"
        return None

    def _has_future_change(self, staff):
        rel_ids = [rel.id for rel in getattr(staff, "_rels", [])]
        if not rel_ids:
            return False
        return HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id__in=rel_ids,
            effective_from__gt=self.as_of,
            status="ACTIVE",
        ).exists()

    def rows(self, params: dict, page: int = 1, page_size: int = 50) -> dict:
        qs = self.apply_filters(self.apply_scope(self.base_qs()), params)
        total = qs.count()
        start = (page - 1) * page_size
        staff_list = list(qs.order_by("staff_no")[start : start + page_size])
        primaries = self._batch_current_primary(staff_list)
        future_flags = self._batch_future_change(staff_list)
        org_names = self._batch_org_names(primaries.values(), as_of=self.as_of)
        items = []
        for staff in staff_list:
            primary = primaries.get(staff.id)
            org_name = None
            if primary and primary.organization_id:
                org_name = (
                    org_names.get(primary.organization_id_id)
                    or primary.organization_id.stable_code
                )
            elif primary and primary.legacy_department_id:
                org_name = f"legacy:{primary.legacy_department_id}"
            items.append(
                self.to_row(
                    staff,
                    primary,
                    org_name=org_name,
                    has_future_change=future_flags.get(staff.id, False),
                )
            )
        return {
            "items": items,
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    def _batch_current_primary(self, staff_list) -> dict:
        staff_ids = [staff.id for staff in staff_list]
        if not staff_ids:
            return {}
        rel_ids = list(
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, staff_id__in=staff_ids, status="ACTIVE"
            ).values_list("id", flat=True)
        )
        if not rel_ids:
            return {}
        assignments = list(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id__in=rel_ids,
                assignment_type=AssignmentType.PRIMARY,
                status="ACTIVE",
            )
            .filter(effective_from__lte=self.as_of)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of))
            .select_related(
                "employment_relationship_id", "organization_id", "position_id", "post_catalog_id"
            )
            .order_by("effective_from")
        )
        by_staff = {}
        for assignment in assignments:
            staff_id = assignment.employment_relationship_id.staff_id_id
            by_staff.setdefault(staff_id, assignment)
        return by_staff

    def _batch_future_change(self, staff_list) -> dict:
        staff_ids = [staff.id for staff in staff_list]
        if not staff_ids:
            return {}
        rel_ids = list(
            HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, staff_id__in=staff_ids
            ).values_list("id", flat=True)
        )
        if not rel_ids:
            return {}
        future_staff_ids = set(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id__in=rel_ids,
                effective_from__gt=self.as_of,
                status="ACTIVE",
            ).values_list("employment_relationship_id__staff_id", flat=True)
        )
        return {staff_id: staff_id in future_staff_ids for staff_id in staff_ids}

    def _batch_org_names(self, primaries, as_of=None) -> dict:
        from hr_structure.models import HrOrganizationVersion
        from hr_structure.selectors.effective import FORMAL_STATUSES

        as_of = as_of or self.as_of
        org_ids = {
            primary.organization_id_id
            for primary in primaries
            if primary and primary.organization_id_id
        }
        if not org_ids:
            return {}
        names = {}
        versions = (
            HrOrganizationVersion.objects.filter(
                tenant_id=self.tenant_id,
                organization_id__in=org_ids,
                status__in=FORMAL_STATUSES,
                validity_from__lte=as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
            .order_by("organization_id_id", "-version_no")
        )
        seen = set()
        for version in versions:
            if version.organization_id_id in seen:
                continue
            seen.add(version.organization_id_id)
            names[version.organization_id_id] = version.name
        return names
