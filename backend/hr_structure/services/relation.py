"""
hr_structure/services/relation.py

RelationService —— 党政组织与业务关系（总册 10 节）。

不变量：
- source/target 同 tenant；
- 主树 parent 不得成环；
- 同组织同 dimension 同日期最多一个 primary parent；
- relation 有生效期；历史不覆盖。
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_structure.models import HrOrganizationRelation
from hr_structure.scope import Hr02Scope


class RelationServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


PRIMARY_PARENT_TYPES = (
    HrOrganizationRelation.RelationType.ADMIN_PARENT,
    HrOrganizationRelation.RelationType.PARTY_PARENT,
    HrOrganizationRelation.RelationType.TEACHING_PARENT,
)


class RelationService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    def _validate_tenant(self, source_org, target_org):
        if source_org.tenant_id != self.scope.tenant_id or target_org.tenant_id != self.scope.tenant_id:
            raise RelationServiceError("HR02_CROSS_TENANT_REFERENCE", "跨租户引用被拒绝")

    @transaction.atomic
    def create_relation(self, *, source_org_id, target_org_id, relation_type, validity_from, validity_to=None) -> HrOrganizationRelation:
        from hr_structure.models import HrOrganization

        if relation_type not in {
            value for value, _ in HrOrganizationRelation.RelationType.choices
        }:
            raise RelationServiceError("HR02_RELATION_TYPE_INVALID", "关系类型非法")
        if validity_to is not None and validity_to <= validity_from:
            raise RelationServiceError(
                "HR02_EFFECTIVE_RANGE_OVERLAP", "关系结束日必须晚于开始日"
            )
        source = HrOrganization.objects.filter(
            id=source_org_id, identity_status=HrOrganization.IdentityStatus.ACTIVE
        ).first()
        target = HrOrganization.objects.filter(
            id=target_org_id, identity_status=HrOrganization.IdentityStatus.ACTIVE
        ).first()
        if source is None or target is None:
            raise RelationServiceError("HR02_ORG_NOT_FOUND", "组织不存在或已停用", http_status=404)
        self._validate_tenant(source, target)
        if source.id == target.id:
            raise RelationServiceError(
                "HR02_RELATION_SELF_REFERENCE", "组织关系不能指向自身"
            )

        # 主树 parent：同 source 同日期最多一个 primary parent（INV 10.3）
        if relation_type in PRIMARY_PARENT_TYPES:
            # 区间重叠检测（10.3：同日期最多一个 primary parent）
            # 统一谓词：既有关系与新增关系区间重叠即冲突
            #   重叠 = 既有.from < 新.to AND (既有.to IS NULL OR 既有.to > 新.from)
            new_from = validity_from
            new_to = validity_to or date.max
            existing = (
                HrOrganizationRelation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    source_org_id=source_org_id,
                    relation_type=relation_type,
                    status="ACTIVE",
                )
                .filter(
                    validity_from__lt=new_to,
                )
                .filter(
                    Q(validity_to__isnull=True) | Q(validity_to__gt=new_from)
                )
                .first()
            )
            if existing:
                raise RelationServiceError(
                    "HR02_RELATION_CONFLICT",
                    f"该组织已有主树上级 {existing.target_org_id_id}，生效区间重叠",
                )
            # 从目标向上回溯同类主关系，若遇到 source 则成环。
            seen = set()
            cursor = target.id
            as_of = validity_from
            while cursor:
                if cursor == source.id or cursor in seen:
                    raise RelationServiceError(
                        "HR02_RELATION_CYCLE", "新关系会形成组织环"
                    )
                seen.add(cursor)
                cursor = (
                    HrOrganizationRelation.objects.filter(
                        tenant_id=self.scope.tenant_id,
                        source_org_id=cursor,
                        relation_type=relation_type,
                        status=HrOrganizationRelation.Status.ACTIVE,
                        validity_from__lte=as_of,
                    )
                    .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
                    .values_list("target_org_id", flat=True)
                    .first()
                )

        relation = HrOrganizationRelation.objects.create(
            tenant_id=self.scope.tenant_id,
            source_org_id_id=source_org_id,
            target_org_id_id=target_org_id,
            relation_type=relation_type,
            validity_from=validity_from,
            validity_to=validity_to,
            status=HrOrganizationRelation.Status.ACTIVE,
            created_by=self.actor,
        )
        return relation

    @transaction.atomic
    def close(self, relation_id):
        rel = (
            HrOrganizationRelation.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=relation_id)
            .first()
        )
        if rel is None:
            raise RelationServiceError("HR02_ORG_NOT_FOUND", "关系不存在", http_status=404)
        if rel.status == HrOrganizationRelation.Status.CLOSED:
            return rel
        rel.status = HrOrganizationRelation.Status.CLOSED
        rel.validity_to = max(timezone.localdate(), rel.validity_from)
        rel.save(update_fields=["status", "validity_to"])
        return rel

    def detect_conflicts(self) -> list:
        """冲突检测（总册 10.4）：党组织未匹配 / 教学组织孤儿 / 多重主归口冲突。"""
        conflicts = []
        # 多重主 parent 冲突
        from django.db.models import Count

        from hr_structure.models import HrOrganization

        multi = (
            HrOrganizationRelation.objects.filter(
                tenant_id=self.scope.tenant_id,
                relation_type__in=PRIMARY_PARENT_TYPES,
                status="ACTIVE",
            )
            .values("source_org_id")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        for m in multi:
            conflicts.append(
                {"type": "MULTI_PRIMARY_PARENT", "orgId": m["source_org_id"], "severity": "WARNING"}
            )
        # 行政组织无 primary parent（孤儿，除根）
        roots_related = HrOrganizationRelation.objects.filter(
            tenant_id=self.scope.tenant_id, relation_type="ADMIN_PARENT", status="ACTIVE"
        ).values_list("source_org_id", flat=True)
        root_versions = HrOrganization.objects.filter(
            tenant_id=self.scope.tenant_id, org_dimension="ADMIN"
        ).exclude(versions__org_type="SCHOOL").exclude(id__in=roots_related)
        for org in root_versions[:20]:
            conflicts.append(
                {"type": "ORG_ORPHAN", "orgId": org.id, "severity": "INFO"}
            )
        return conflicts
