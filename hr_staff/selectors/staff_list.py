"""
hr_staff/selectors/staff_list.py —— HR03-01 名册查询（只读，S4）。

硬合同（总册 §10 / §35）：
- tenant → scope → permission → 字段策略四层后才有数据；
- 只返回当前 as_of（默认今天）的当前人事事实，不伪装历史；
- 高敏字段（HIGH_SENSITIVE）默认不进列表 API；RESTRICTED/SENSITIVE 按权限裁剪；
- 服务器端翻译为受控 QuerySpec，不接收任意 ORM field path；
- select_related/prefetch 预算：名册 50 行 ≤ 10~15 SQL。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db.models import Q, Prefetch

from hr_staff.constants import AssignmentType, StaffStatus
from hr_staff.context import HrStaffRequestContext
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment, HrStaffMaster
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


# 名册默认可见字段（PUBLIC_HR；字段裁剪由 API 层二次执行）
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
        self.as_of = context.as_of or date.today()

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
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
        if scope.scope_type in ("SCHOOL", "SELF", "ASSIGNMENT", "EXPLICIT_STAFF_SET"):
            return None
        if scope.org_id is None:
            return None
        try:
            from hr_structure.selectors.effective import build_tree_as_of

            nodes = build_tree_as_of(self.tenant_id, scope.org_id, self.as_of, depth_limit=6)
            return {n["id"] for n in nodes} | {scope.org_id}
        except Exception:
            return {scope.org_id}

    # ------------------------------------------------------------------
    # 过滤（受控 QuerySpec）
    # ------------------------------------------------------------------
    def apply_scope(self, qs):
        scope = self.context.scope
        if scope.scope_type == "SELF" and scope.staff_ids:
            return qs.filter(id__in=scope.staff_ids)
        if scope.scope_type == "EXPLICIT_STAFF_SET" and scope.staff_ids:
            return qs.filter(id__in=scope.staff_ids)
        org_ids = self._scope_org_ids()
        if org_ids:
            today_primary_orgs = HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                assignment_type=AssignmentType.PRIMARY,
                effective_from__lte=self.as_of,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of)
            ).filter(organization_id__in=org_ids).values_list(
                "employment_relationship_id__staff_id", flat=True
            )
            return qs.filter(id__in=today_primary_orgs)
        return qs

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
            rel_staff_ids = HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id,
                relationship_type=relationship_type,
                status="ACTIVE",
                effective_from__lte=self.as_of,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=self.as_of)
            ).values_list("staff_id", flat=True)
            qs = qs.filter(id__in=rel_staff_ids)

        joining_from = params.get("joining_from")
        joining_to = params.get("joining_to")
        if joining_from or joining_to:
            q = Q()
            if joining_from:
                q &= Q(employment_relationships__effective_from__gte=joining_from)
            if joining_to:
                q &= Q(employment_relationships__effective_from__lte=joining_to)
            qs = qs.filter(q).distinct()

        has_future = params.get("has_future_change")
        if has_future in ("1", "true", "True"):
            future_staff_ids = (
                HrEmploymentRelationship.objects.filter(
                    tenant_id=self.tenant_id, effective_from__gt=self.as_of
                ).values_list("staff_id", flat=True)
            )
            qs = qs.filter(id__in=future_staff_ids)
        return qs

    # ------------------------------------------------------------------
    # 行组装
    # ------------------------------------------------------------------
    def _current_primary(self, staff):
        """从 prefetch 的关系段反查当前主岗（避免 N+1）。"""
        rel_ids = [rel.id for rel in getattr(staff, "_rels", []) if rel.status == "ACTIVE"]
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
        rels = [r for r in getattr(staff, "_rels", []) if r.effective_from is not None]
        return min((r.effective_from for r in rels), default=None)

    def to_row(self, staff, primary, *, org_name=None, has_future_change=False) -> dict:
        row = {
            "staff_id": str(staff.id),
            "staff_uid": str(staff.staff_uid),
            "staff_no": staff.staff_no,
            "legal_name": staff.person_id.legal_name,
            "preferred_name": staff.person_id.preferred_name,
            "staff_category_code": staff.staff_category_code,
            "current_employment_status": staff.current_employment_status or "PENDING_ENTRY",
            "org_id": str(primary.organization_id_id) if primary and primary.organization_id else None,
            "org_name": org_name if org_name is not None else self._org_display(primary),
            "position_name": (
                primary.position_id.position_code
                if primary and primary.position_id
                else None
            ),
            "primary_assignment_type": "PRIMARY",
            "date_joining": self._earliest_joining(staff).isoformat() if self._earliest_joining(staff) else None,
            "relationship_type": (
                getattr(staff._rels[0], "relationship_type", None)
                if getattr(staff, "_rels", None)
                else None
            ),
            "has_future_change": has_future_change,
        }
        return row

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
        # P2-N+1：批量预取当前 PRIMARY + 未来变更 + 组织名（3 次批量查询，不再逐行）
        primaries = self._batch_current_primary(staff_list)
        future_flags = self._batch_future_change(staff_list)
        org_names = self._batch_org_names(primaries.values(), as_of=self.as_of)
        items = []
        for staff in staff_list:
            primary = primaries.get(staff.id)
            # 批量路径不回退到 _org_display（避免 N+1）：batch 未命中则用 stable_code/legacy 直显
            org_name = None
            if primary and primary.organization_id:
                org_name = org_names.get(primary.organization_id_id) or primary.organization_id.stable_code
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
        """按 staff 批量取当前 PRIMARY（一次查询）。"""
        staff_ids = [s.id for s in staff_list]
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
            .select_related("organization_id", "position_id", "post_catalog_id")
            .order_by("effective_from")
        )
        by_staff = {}
        for a in assignments:
            sid = a.employment_relationship_id.staff_id_id
            by_staff.setdefault(sid, a)
        return by_staff

    def _batch_future_change(self, staff_list) -> dict:
        staff_ids = [s.id for s in staff_list]
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
        return {sid: sid in future_staff_ids for sid in staff_ids}

    def _batch_org_names(self, primaries, as_of=None) -> dict:
        """批量解析组织 as-of 名称（一次 HR02 查询，带 tenant 防泄漏）。"""
        from datetime import date as _date

        from django.db.models import Q

        from hr_structure.models import HrOrganizationVersion

        as_of = as_of or _date.today()
        org_ids = {
            p.organization_id_id
            for p in primaries
            if p and p.organization_id_id
        }
        if not org_ids:
            return {}
        names = {}
        versions = (
            HrOrganizationVersion.objects.filter(
                tenant_id=self.tenant_id,
                organization_id__in=org_ids,
            )
            .filter(
                validity_from__lte=as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
            .order_by("organization_id_id", "-version_no")
        )
        seen = set()
        for v in versions:
            if v.organization_id_id in seen:
                continue
            seen.add(v.organization_id_id)
            names[v.organization_id_id] = v.name
        return names
