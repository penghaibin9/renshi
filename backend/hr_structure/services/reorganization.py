"""
hr_structure/services/reorganization.py

ReorganizationService —— 组织历史与重组（总册 14 节）。

- case 状态机：DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → SCHEDULED → EFFECTIVE
- 影响分析（50.7 依赖矩阵）：下级组织/岗位/编制/预占/HR03 任职
- effective runner：到期生效（幂等 execution key）
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from horilla.hr_event_service import emit_registered_event

from hr_structure.authority_registry import (
    EVENT_ORGANIZATION_CHANGED,
    EVENT_ORGANIZATION_CREATED,
    EVENT_POSITION_CREATED,
    EVENT_POSITION_STATUS_CHANGED,
    EVENT_REORGANIZATION_EFFECTIVE,
)
from hr_structure.models import HrStructureChangeCase, HrStructureChangeItem
from hr_structure.scope import Hr02Scope


class ReorgServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ReorganizationService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    @staticmethod
    def _payload_value(payload, *names, default=None):
        for name in names:
            if name in payload:
                return payload[name]
        return default

    @staticmethod
    def _payload_bool(value):
        if isinstance(value, bool):
            return value
        if value in (1, "1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
            return True
        if value in (0, "0", "false", "FALSE", "False", "no", "NO", "off", "OFF"):
            return False
        raise ValueError("布尔值格式非法")

    @staticmethod
    def _integer_value(value, label, *, minimum=0):
        try:
            parsed = Decimal(str(value))
            if parsed < minimum or parsed != parsed.to_integral_value():
                raise InvalidOperation
            return int(parsed)
        except (InvalidOperation, TypeError, ValueError):
            qualifier = "正整数" if minimum == 1 else "非负整数"
            raise ValueError(f"{label} 必须是{qualifier}")

    def _item_contract_blockers(self, item, effective_date) -> list[tuple[str, str]]:
        """Return stable blockers before a case can leave DRAFT.

        The execution runner re-runs these checks to protect approved cases from
        item tampering between approval and the effective date.
        """
        from hr_staff.models import HrStaffAssignment

        from hr_structure.models import (
            HrHeadcountQuotaLine,
            HrOrganization,
            HrOrganizationRelation,
            HrOrganizationVersion,
            HrPosition,
            HrPositionQuotaLine,
            HrPositionReservation,
            HrPostCatalogVersion,
        )
        from hr_structure.selectors.effective import org_version_as_of

        action = getattr(item, "action_type", "")
        if not action:
            return []
        payload = getattr(item, "after_payload", None) or {}
        blockers = []

        def require(code, names, label):
            value = self._payload_value(payload, *names)
            if value in (None, "") or (
                isinstance(value, str) and not value.strip()
            ):
                blockers.append((code, f"{action} 缺少 {label}"))
            return value

        def entity_id():
            try:
                return int(item.entity_id)
            except (TypeError, ValueError):
                blockers.append(("REORG_ENTITY_ID_REQUIRED", f"{action} 缺少有效 entity_id"))
                return None

        def organization(org_id, label):
            if org_id in (None, ""):
                blockers.append(("REORG_TARGET_ORG_REQUIRED", f"{action} 缺少 {label}"))
                return None
            try:
                org_id = int(org_id)
            except (TypeError, ValueError):
                blockers.append(("REORG_TARGET_ORG_INVALID", f"{label} 必须是组织 ID"))
                return None
            org = HrOrganization.objects.filter(
                tenant_id=self.scope.tenant_id,
                id=org_id,
                identity_status=HrOrganization.IdentityStatus.ACTIVE,
            ).first()
            if org is None or org_version_as_of(
                self.scope.tenant_id, org_id, effective_date
            ) is None:
                blockers.append(("REORG_TARGET_ORG_NOT_EFFECTIVE", f"{label} 在生效日不可用"))
                return None
            return org

        def any_organization(org_id, label):
            if org_id in (None, ""):
                blockers.append(("REORG_TARGET_ORG_REQUIRED", f"{action} 缺少 {label}"))
                return None
            try:
                org_id = int(org_id)
            except (TypeError, ValueError):
                blockers.append(("REORG_TARGET_ORG_INVALID", f"{label} 必须是组织 ID"))
                return None
            org = HrOrganization.objects.filter(
                tenant_id=self.scope.tenant_id, id=org_id
            ).first()
            if org is None:
                blockers.append(("REORG_TARGET_ORG_NOT_FOUND", f"{label} 不存在或跨租户"))
            return org

        def position(position_id):
            pos = HrPosition.objects.filter(
                tenant_id=self.scope.tenant_id, id=position_id
            ).first()
            if pos is None:
                blockers.append(("REORG_POSITION_NOT_FOUND", f"岗位 {position_id} 不存在或跨租户"))
            return pos

        def relation(relation_id):
            rel = HrOrganizationRelation.objects.filter(
                tenant_id=self.scope.tenant_id, id=relation_id
            ).first()
            if rel is None:
                blockers.append(("REORG_RELATION_NOT_FOUND", f"组织关系 {relation_id} 不存在或跨租户"))
            return rel

        def active_assignments_for_org(org_id):
            return HrStaffAssignment.objects.filter(
                tenant_id=self.scope.tenant_id,
                organization_id=org_id,
                status="ACTIVE",
                effective_from__lte=effective_date,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=effective_date)
            ).count()

        def mapped_entity_ids(action_type, *, target_ids=None):
            """Return entities explicitly mapped by sibling items in this case."""
            case_id = getattr(item, "case_id_id", None)
            if not case_id:
                return set()
            result = set()
            for sibling in HrStructureChangeItem.objects.filter(
                case_id_id=case_id, action_type=action_type
            ):
                if not str(sibling.entity_id or "").isdigit():
                    continue
                sibling_payload = sibling.after_payload or {}
                if target_ids is not None:
                    raw_target = self._payload_value(
                        sibling_payload,
                        "target_organization_id",
                        "targetOrganizationId",
                        "organization_id",
                        "organizationId",
                        "target_parent_id",
                        "targetParentId",
                        "parent_organization_id",
                        "parentOrganizationId",
                    )
                    try:
                        raw_target = int(raw_target)
                    except (TypeError, ValueError):
                        continue
                    if raw_target not in target_ids:
                        continue
                result.add(int(sibling.entity_id))
            return result

        def destructive_org_blockers(org, *, target_ids=None):
            """Require explicit mappings before closing a stable organization."""
            if not org:
                return
            if org_version_as_of(
                self.scope.tenant_id, org.id, effective_date
            ).org_type == HrOrganizationVersion.OrgType.SCHOOL:
                blockers.append(("REORG_ROOT_ORG_IMMUTABLE", "学校根组织不能停用、合并或拆分"))

            child_ids = set(
                HrOrganizationVersion.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    parent_organization_id=org.id,
                    status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                    validity_from__lte=effective_date,
                )
                .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date))
                .values_list("organization_id", flat=True)
            )
            mapped_children = mapped_entity_ids("REPARENT_ORG", target_ids=target_ids)
            missing_children = child_ids - mapped_children
            if missing_children:
                blockers.append((
                    "REORG_CHILD_MAPPING_INCOMPLETE",
                    f"组织 {org.id} 还有 {len(missing_children)} 个下级未在本 case 中明确迁移",
                ))

            position_ids = set(
                HrPosition.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    organization_id=org.id,
                )
                .exclude(
                    lifecycle_status__in=(
                        HrPosition.LifecycleStatus.CLOSED,
                        HrPosition.LifecycleStatus.CANCELLED,
                    )
                )
                .values_list("id", flat=True)
            )
            mapped_positions = mapped_entity_ids("MOVE_POSITION", target_ids=target_ids)
            missing_positions = position_ids - mapped_positions
            if missing_positions:
                blockers.append((
                    "REORG_POSITION_MAPPING_INCOMPLETE",
                    f"组织 {org.id} 还有 {len(missing_positions)} 个岗位未在本 case 中明确迁移",
                ))

            assignment_count = active_assignments_for_org(org.id)
            if assignment_count:
                blockers.append((
                    "REORG_STAFF_ASSIGNMENTS_UNRESOLVED",
                    f"组织 {org.id} 生效日有 {assignment_count} 条任职，需先通过 HR03 正式异动",
                ))
            held = HrPositionReservation.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_id__organization_id=org.id,
                status=HrPositionReservation.Status.HELD,
            ).count()
            if held:
                blockers.append((
                    "REORG_HELD_RESERVATIONS_UNRESOLVED",
                    f"组织 {org.id} 有 {held} 条未处理岗位预占",
                ))

            protected_plan_statuses = ("UNDER_REVIEW", "APPROVED", "EFFECTIVE")
            quota_count = HrHeadcountQuotaLine.objects.filter(
                tenant_id=self.scope.tenant_id,
                organization_id=org.id,
                plan_id__status__in=protected_plan_statuses,
            ).count() + HrPositionQuotaLine.objects.filter(
                tenant_id=self.scope.tenant_id,
                organization_id=org.id,
                plan_id__status__in=protected_plan_statuses,
            ).count()
            if quota_count:
                blockers.append((
                    "REORG_QUOTA_MAPPING_INCOMPLETE",
                    f"组织 {org.id} 有 {quota_count} 条已提交或正式编制额度，需先完成方案调整",
                ))

        if action == "CREATE_ORG":
            stable_code = require("CREATE_ORG_STABLE_CODE_REQUIRED", ("stable_code", "stableCode"), "stable_code")
            require("CREATE_ORG_NAME_REQUIRED", ("name",), "name")
            org_type = require("CREATE_ORG_TYPE_REQUIRED", ("org_type", "orgType"), "org_type")
            dimension = require("CREATE_ORG_DIMENSION_REQUIRED", ("dimension", "org_dimension", "orgDimension"), "dimension")
            if org_type and org_type not in {value for value, _ in HrOrganizationVersion.OrgType.choices}:
                blockers.append(("CREATE_ORG_TYPE_INVALID", "CREATE_ORG org_type 非法"))
            if dimension and dimension not in {value for value, _ in HrOrganization.Dimension.choices}:
                blockers.append(("CREATE_ORG_DIMENSION_INVALID", "CREATE_ORG dimension 非法"))
            if stable_code and HrOrganization.objects.filter(
                tenant_id=self.scope.tenant_id, stable_code=stable_code
            ).exists():
                blockers.append(("CREATE_ORG_CODE_CONFLICT", f"stable_code {stable_code} 已存在"))
            parent_id = self._payload_value(payload, "parent_organization_id", "parentOrganizationId", "parent_id", "parentId")
            if org_type != HrOrganizationVersion.OrgType.SCHOOL:
                organization(parent_id, "parent_organization_id")
            elif parent_id not in (None, ""):
                blockers.append(("CREATE_ORG_SCHOOL_PARENT_INVALID", "SCHOOL 根组织不能有上级"))
            elif HrOrganizationVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                org_type=HrOrganizationVersion.OrgType.SCHOOL,
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            ).exists():
                blockers.append(("CREATE_ORG_SCHOOL_CONFLICT", "该租户已存在 SCHOOL 根组织"))
            try:
                int(self._payload_value(payload, "sort_order", "sortOrder", default=0) or 0)
            except (TypeError, ValueError):
                blockers.append(("CREATE_ORG_SORT_ORDER_INVALID", "sort_order 必须是整数"))

        elif action == "RENAME_ORG":
            org_id = entity_id()
            organization(org_id, "organization_id") if org_id else None
            require("RENAME_ORG_NAME_REQUIRED", ("name",), "name")

        elif action == "CHANGE_ORG_TYPE":
            org_id = entity_id()
            org = organization(org_id, "organization_id") if org_id else None
            org_type = require(
                "CHANGE_ORG_TYPE_REQUIRED", ("org_type", "orgType"), "org_type"
            )
            if org_type and org_type not in {
                value for value, _ in HrOrganizationVersion.OrgType.choices
            }:
                blockers.append(("CHANGE_ORG_TYPE_INVALID", "org_type 非法"))
            current_version = (
                org_version_as_of(self.scope.tenant_id, org.id, effective_date)
                if org
                else None
            )
            if current_version and current_version.org_type == org_type:
                blockers.append(("CHANGE_ORG_TYPE_NO_CHANGE", "组织类型未发生变化"))
            if org_type == HrOrganizationVersion.OrgType.SCHOOL:
                if current_version and current_version.parent_organization_id_id:
                    blockers.append(("CHANGE_ORG_TYPE_ROOT_INVALID", "SCHOOL 组织不能有上级"))
                if HrOrganizationVersion.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    org_type=HrOrganizationVersion.OrgType.SCHOOL,
                    validity_from__lte=effective_date,
                ).filter(
                    Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date)
                ).exclude(organization_id=org_id).exists():
                    blockers.append(("CHANGE_ORG_TYPE_SCHOOL_CONFLICT", "该租户已有 SCHOOL 根组织"))

        elif action == "REPARENT_ORG":
            org_id = entity_id()
            current = organization(org_id, "organization_id") if org_id else None
            parent_present = any(
                key in payload
                for key in ("parent_organization_id", "parentOrganizationId", "target_parent_id", "targetParentId")
            )
            if not parent_present:
                blockers.append(("REPARENT_TARGET_REQUIRED", "REPARENT_ORG 必须显式提供新上级"))
            else:
                parent_id = self._payload_value(payload, "parent_organization_id", "parentOrganizationId", "target_parent_id", "targetParentId")
                if parent_id in (None, ""):
                    current_version = (
                        org_version_as_of(self.scope.tenant_id, org_id, effective_date)
                        if org_id else None
                    )
                    if current_version and current_version.org_type != HrOrganizationVersion.OrgType.SCHOOL:
                        blockers.append(("REPARENT_ROOT_INVALID", "仅 SCHOOL 可调整为根组织"))
                else:
                    parent = organization(parent_id, "target_parent_id")
                    if current and parent and current.id == parent.id:
                        blockers.append(("REPARENT_CYCLE", "组织不能挂到自身"))
                    elif current and parent:
                        seen = set()
                        cursor = parent.id
                        while cursor:
                            if cursor == current.id or cursor in seen:
                                blockers.append(("REPARENT_CYCLE", "调整上级会形成组织环"))
                                break
                            seen.add(cursor)
                            version = org_version_as_of(
                                self.scope.tenant_id, cursor, effective_date
                            )
                            cursor = (
                                version.parent_organization_id_id if version else None
                            )

        elif action == "DEACTIVATE_ORG":
            org_id = entity_id()
            org = organization(org_id, "organization_id") if org_id else None
            destructive_org_blockers(org)

        elif action == "REACTIVATE_ORG":
            org_id = entity_id()
            org = any_organization(org_id, "organization_id") if org_id else None
            if org and org.identity_status != HrOrganization.IdentityStatus.CLOSED:
                blockers.append(("REACTIVATE_ORG_NOT_CLOSED", "仅已停用组织可重新启用"))
            latest = (
                HrOrganizationVersion.objects.filter(
                    tenant_id=self.scope.tenant_id, organization_id=org_id
                ).order_by("-version_no").first()
                if org_id
                else None
            )
            if org and latest is None:
                blockers.append(("REACTIVATE_ORG_VERSION_MISSING", "组织缺少可恢复的历史版本"))
            parent_id = self._payload_value(
                payload,
                "parent_organization_id",
                "parentOrganizationId",
                default=latest.parent_organization_id_id if latest else None,
            )
            if latest and latest.org_type != HrOrganizationVersion.OrgType.SCHOOL:
                organization(parent_id, "parent_organization_id")

        elif action in {"CREATE_RELATION", "CHANGE_RELATION"}:
            relation_type = require(
                "REORG_RELATION_TYPE_REQUIRED",
                ("relation_type", "relationType"),
                "relation_type",
            )
            if relation_type and relation_type not in {
                value for value, _ in HrOrganizationRelation.RelationType.choices
            }:
                blockers.append(("REORG_RELATION_TYPE_INVALID", "relation_type 非法"))
            if action == "CREATE_RELATION":
                source_id = entity_id()
                source = organization(source_id, "source_organization_id") if source_id else None
            else:
                relation_id = entity_id()
                current_relation = relation(relation_id) if relation_id else None
                source = (
                    organization(current_relation.source_org_id_id, "source_organization_id")
                    if current_relation
                    else None
                )
                if current_relation and current_relation.status != HrOrganizationRelation.Status.ACTIVE:
                    blockers.append(("CHANGE_RELATION_NOT_ACTIVE", "仅生效中的组织关系可变更"))
                if current_relation and effective_date < current_relation.validity_from:
                    blockers.append(("REORG_RELATION_BOUNDARY_INVALID", "关系变更日不得早于原关系开始日"))
                if current_relation and relation_type != current_relation.relation_type:
                    blockers.append((
                        "CHANGE_RELATION_TYPE_IMMUTABLE",
                        "关系类型不可在变更中换类，请关闭后新建",
                    ))
            target_id = require(
                "REORG_RELATION_TARGET_REQUIRED",
                ("target_organization_id", "targetOrganizationId", "target_org_id", "targetOrgId"),
                "target_organization_id",
            )
            target = organization(target_id, "target_organization_id") if target_id else None
            if source and target and source.id == target.id:
                blockers.append(("REORG_RELATION_SELF_REFERENCE", "组织关系不能指向自身"))
            if source and target and relation_type in {
                HrOrganizationRelation.RelationType.ADMIN_PARENT,
                HrOrganizationRelation.RelationType.PARTY_PARENT,
                HrOrganizationRelation.RelationType.TEACHING_PARENT,
            }:
                seen = set()
                cursor = target.id
                while cursor:
                    if cursor == source.id or cursor in seen:
                        blockers.append(("REORG_RELATION_CYCLE", "关系变更会形成组织环"))
                        break
                    seen.add(cursor)
                    cursor = (
                        HrOrganizationRelation.objects.filter(
                            tenant_id=self.scope.tenant_id,
                            source_org_id=cursor,
                            relation_type=relation_type,
                            status=HrOrganizationRelation.Status.ACTIVE,
                            validity_from__lte=effective_date,
                        )
                        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date))
                        .values_list("target_org_id", flat=True)
                        .first()
                    )
                excluded_id = current_relation.id if action == "CHANGE_RELATION" and current_relation else None
                conflicts = HrOrganizationRelation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    source_org_id=source.id,
                    relation_type=relation_type,
                    status=HrOrganizationRelation.Status.ACTIVE,
                    validity_from__lt=date.max,
                ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date))
                if excluded_id:
                    conflicts = conflicts.exclude(id=excluded_id)
                if conflicts.exists():
                    blockers.append(("REORG_RELATION_CONFLICT", "生效日已存在重叠的主关系"))

        elif action == "CREATE_POSITION":
            position_code = require("CREATE_POSITION_CODE_REQUIRED", ("position_code", "positionCode"), "position_code")
            org_id = require("CREATE_POSITION_ORG_REQUIRED", ("organization_id", "organizationId"), "organization_id")
            catalog_id = require("CREATE_POSITION_CATALOG_REQUIRED", ("post_catalog_version_id", "postCatalogVersionId"), "post_catalog_version_id")
            organization(org_id, "organization_id") if org_id else None
            if position_code and HrPosition.objects.filter(
                tenant_id=self.scope.tenant_id,
                position_code=position_code,
            ).exists():
                blockers.append(("CREATE_POSITION_CODE_CONFLICT", f"position_code {position_code} 已存在"))
            if catalog_id:
                try:
                    catalog = HrPostCatalogVersion.objects.filter(
                        tenant_id=self.scope.tenant_id,
                        id=int(catalog_id),
                        status=HrPostCatalogVersion.Status.ACTIVE,
                        validity_from__lte=effective_date,
                    ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date)).first()
                except (TypeError, ValueError):
                    catalog = None
                if catalog is None:
                    blockers.append(("CREATE_POSITION_CATALOG_NOT_EFFECTIVE", "岗位目录版本不存在、跨租户或生效日不可用"))
            position_type = self._payload_value(
                payload,
                "position_type",
                "positionType",
                default=HrPosition.PositionType.REGULAR,
            )
            if position_type not in {value for value, _ in HrPosition.PositionType.choices}:
                blockers.append(("CREATE_POSITION_TYPE_INVALID", "position_type 非法"))
            try:
                planned_fte = Decimal(
                    str(
                        self._payload_value(
                            payload, "planned_fte", "plannedFte", default="1.00"
                        )
                    )
                )
                if planned_fte <= 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                blockers.append(("CREATE_POSITION_FTE_INVALID", "planned_fte 必须大于 0"))
            try:
                self._integer_value(
                    self._payload_value(
                        payload, "max_incumbents", "maxIncumbents", default=1
                    ),
                    "max_incumbents",
                    minimum=1,
                )
            except ValueError:
                blockers.append(("CREATE_POSITION_CAPACITY_INVALID", "max_incumbents 必须是正整数"))

        elif action in {"MOVE_POSITION", "CHANGE_POSITION", "CLOSE_POSITION"}:
            position_id = entity_id()
            pos = position(position_id) if position_id else None
            if pos and pos.lifecycle_status in {
                HrPosition.LifecycleStatus.CLOSED,
                HrPosition.LifecycleStatus.CANCELLED,
            }:
                blockers.append(("REORG_POSITION_TERMINAL", f"岗位 {position_id} 已是终态"))
            if action == "MOVE_POSITION":
                target_id = require("MOVE_POSITION_TARGET_REQUIRED", ("organization_id", "organizationId", "target_organization_id", "targetOrganizationId"), "target organization")
                target = organization(target_id, "target_organization_id") if target_id else None
                if pos and target and pos.organization_id_id == target.id:
                    blockers.append(("MOVE_POSITION_NO_CHANGE", "岗位已属于目标组织"))
            if action == "CHANGE_POSITION" and pos:
                allowed_keys = {
                    "post_catalog_version_id", "postCatalogVersionId",
                    "post_grade_id", "postGradeId", "position_type", "positionType",
                    "planned_fte", "plannedFte", "max_incumbents", "maxIncumbents",
                    "allow_multiple_incumbents", "allowMultipleIncumbents",
                    "lifecycle_status", "lifecycleStatus", "freeze_reason", "freezeReason",
                }
                if not any(key in payload for key in allowed_keys):
                    blockers.append(("CHANGE_POSITION_PAYLOAD_REQUIRED", "CHANGE_POSITION 未提供可变更字段"))
                catalog_id = self._payload_value(payload, "post_catalog_version_id", "postCatalogVersionId")
                if catalog_id not in (None, ""):
                    try:
                        catalog_ok = HrPostCatalogVersion.objects.filter(
                            tenant_id=self.scope.tenant_id,
                            id=int(catalog_id),
                            status=HrPostCatalogVersion.Status.ACTIVE,
                            validity_from__lte=effective_date,
                        ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date)).exists()
                    except (TypeError, ValueError):
                        catalog_ok = False
                    if not catalog_ok:
                        blockers.append(("CHANGE_POSITION_CATALOG_NOT_EFFECTIVE", "岗位目录版本不可用"))
                position_type = self._payload_value(payload, "position_type", "positionType")
                if position_type and position_type not in {value for value, _ in HrPosition.PositionType.choices}:
                    blockers.append(("CHANGE_POSITION_TYPE_INVALID", "position_type 非法"))
                lifecycle = self._payload_value(payload, "lifecycle_status", "lifecycleStatus")
                if lifecycle and lifecycle not in {
                    HrPosition.LifecycleStatus.ACTIVE,
                    HrPosition.LifecycleStatus.FROZEN,
                }:
                    blockers.append(("CHANGE_POSITION_STATUS_INVALID", "CHANGE_POSITION 仅支持激活/冻结，关闭请使用 CLOSE_POSITION"))
                allow_multiple = self._payload_value(
                    payload, "allow_multiple_incumbents", "allowMultipleIncumbents"
                )
                if allow_multiple is not None:
                    try:
                        self._payload_bool(allow_multiple)
                    except ValueError:
                        blockers.append((
                            "CHANGE_POSITION_MULTI_FLAG_INVALID",
                            "allow_multiple_incumbents 必须是布尔值",
                        ))
                try:
                    new_fte = Decimal(str(self._payload_value(payload, "planned_fte", "plannedFte", default=pos.planned_fte)))
                    if new_fte <= 0:
                        raise InvalidOperation
                except (InvalidOperation, TypeError, ValueError):
                    blockers.append(("CHANGE_POSITION_FTE_INVALID", "planned_fte 必须大于 0"))
                try:
                    capacity = self._integer_value(
                        self._payload_value(
                            payload,
                            "max_incumbents",
                            "maxIncumbents",
                            default=pos.max_incumbents,
                        ),
                        "max_incumbents",
                        minimum=1,
                    )
                    occupied = HrStaffAssignment.objects.filter(
                        tenant_id=self.scope.tenant_id,
                        position_id=pos.id,
                        status="ACTIVE",
                        effective_from__lte=effective_date,
                    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_date)).count()
                    if capacity < occupied:
                        blockers.append(("CHANGE_POSITION_CAPACITY_CONFLICT", f"岗位上限 {capacity} 低于生效日在岗人数 {occupied}"))
                except ValueError:
                    blockers.append(("CHANGE_POSITION_CAPACITY_INVALID", "max_incumbents 必须是正整数"))
            if pos and action in {"MOVE_POSITION", "CLOSE_POSITION"}:
                active_assignments = HrStaffAssignment.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    position_id=pos.id,
                    status="ACTIVE",
                    effective_from__lte=effective_date,
                ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_date)).count()
                if active_assignments:
                    blockers.append(("POSITION_HAS_ACTIVE_ASSIGNMENTS", f"岗位 {pos.id} 生效日有 {active_assignments} 条任职，需先通过 HR03 异动"))
                held = HrPositionReservation.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    position_id=pos.id,
                    status=HrPositionReservation.Status.HELD,
                ).count()
                if held:
                    blockers.append(("POSITION_HAS_HELD_RESERVATIONS", f"岗位 {pos.id} 有 {held} 条未处理预占"))

        elif action in {"ADJUST_STAFFING_QUOTA", "ADJUST_POSITION_QUOTA"}:
            line_id = entity_id()
            if action == "ADJUST_STAFFING_QUOTA":
                line = HrHeadcountQuotaLine.objects.filter(
                    tenant_id=self.scope.tenant_id, id=line_id
                ).select_related("plan_id").first() if line_id else None
                required_names = ("authorized_headcount", "authorizedHeadcount")
                field_label = "authorized_headcount"
            else:
                line = HrPositionQuotaLine.objects.filter(
                    tenant_id=self.scope.tenant_id, id=line_id
                ).select_related("plan_id").first() if line_id else None
                required_names = ("authorized_positions", "authorizedPositions")
                field_label = "authorized_positions"
            if line is None and line_id:
                blockers.append(("REORG_QUOTA_LINE_NOT_FOUND", "编制额度行不存在或跨租户"))
            elif line and line.plan_id.status != "DRAFT":
                blockers.append(("REORG_QUOTA_PLAN_LOCKED", "仅草稿编制方案可调整，正式方案必须建新版本"))
            raw_count = require("REORG_QUOTA_VALUE_REQUIRED", required_names, field_label)
            try:
                self._integer_value(raw_count, field_label)
            except ValueError:
                blockers.append(("REORG_QUOTA_VALUE_INVALID", f"{field_label} 必须是非负整数"))
            raw_fte = self._payload_value(payload, "authorized_fte", "authorizedFte")
            if raw_fte is not None:
                try:
                    if Decimal(str(raw_fte)) < 0:
                        raise InvalidOperation
                except (InvalidOperation, TypeError, ValueError):
                    blockers.append(("REORG_QUOTA_FTE_INVALID", "authorized_fte 必须是非负数"))
            reserve = self._payload_value(payload, "reserve_headcount", "reserveHeadcount")
            if reserve is not None:
                try:
                    self._integer_value(reserve, "reserve_headcount")
                except ValueError:
                    blockers.append((
                        "REORG_RESERVE_QUOTA_INVALID",
                        "reserve_headcount 必须是非负整数",
                    ))
            control_mode = self._payload_value(payload, "control_mode", "controlMode")
            if control_mode is not None and control_mode not in {
                "HARD", "SOFT", "INFO_ONLY"
            }:
                blockers.append((
                    "REORG_QUOTA_CONTROL_MODE_INVALID", "control_mode 非法"
                ))

        elif action == "MERGE_ORGS":
            source_id = entity_id()
            source = organization(source_id, "source_organization_id") if source_id else None
            target_id = require(
                "MERGE_TARGET_REQUIRED",
                ("target_organization_id", "targetOrganizationId"),
                "target_organization_id",
            )
            target = organization(target_id, "target_organization_id") if target_id else None
            if source and target and source.id == target.id:
                blockers.append(("MERGE_TARGET_SAME_AS_SOURCE", "合并目标不能与源组织相同"))
            if source and target:
                destructive_org_blockers(source, target_ids={target.id})

        elif action == "SPLIT_ORG":
            source_id = entity_id()
            source = organization(source_id, "source_organization_id") if source_id else None
            raw_targets = require(
                "SPLIT_TARGETS_REQUIRED",
                ("target_organization_ids", "targetOrganizationIds"),
                "target_organization_ids",
            )
            target_ids = set()
            if not isinstance(raw_targets, list) or len(raw_targets) < 2:
                blockers.append(("SPLIT_TARGETS_INVALID", "拆分必须明确指定至少两个目标组织"))
            else:
                for raw_target in raw_targets:
                    target = organization(raw_target, "target_organization_id")
                    if target:
                        target_ids.add(target.id)
                if source and source.id in target_ids:
                    blockers.append(("SPLIT_TARGET_SAME_AS_SOURCE", "拆分目标不能包含源组织"))
            if source and len(target_ids) >= 2:
                destructive_org_blockers(source, target_ids=target_ids)
        else:
            blockers.append(("REORG_ACTION_UNSUPPORTED", f"action {action} 尚无安全执行合同"))
        return blockers

    def impact_analysis(self, case: HrStructureChangeCase) -> dict:
        """影响分析（总册 14.8 / 50.7 依赖矩阵）。

        返回 BLOCKER / REQUIRES_MAPPING / WARNING / SAFE 分类。
        HR03 任职使用正式任职事实按计划生效日计算；其他下游保持显式契约边界。
        """
        from hr_staff.models import HrStaffAssignment

        from hr_structure.models import (
            HrOrganizationVersion,
            HrPosition,
            HrPositionReservation,
        )

        items = list(case.items.all())
        org_ids = set()
        for item in items:
            if item.entity_type == "org" and str(item.entity_id or "").isdigit():
                org_ids.add(int(item.entity_id))

        result = {"summary": {"blocker": 0, "requiresMapping": 0, "warning": 0, "safe": 0}, "checks": []}

        def add(level, code, message):
            key = "requiresMapping" if level == "REQUIRES_MAPPING" else level.lower()
            result["summary"][key] += 1
            result["checks"].append({"level": level, "code": code, "message": message})

        for item in items:
            blockers = self._item_contract_blockers(
                item, case.requested_effective_date
            )
            if blockers:
                item.validation_status = "BLOCKED"
                for code, message in blockers:
                    add("BLOCKER", code, message)
            else:
                item.validation_status = "VALID"

        for org_id in org_ids:
            # 下级组织
            child_count = HrOrganizationVersion.objects.filter(
                tenant_id=self.scope.tenant_id,
                parent_organization_id=org_id,
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                validity_to__isnull=True,
            ).count()
            if child_count:
                add("REQUIRES_MAPPING", "ORG_HAS_CHILDREN", f"组织 {org_id} 有 {child_count} 个下级，需确认迁移方案")
            # 岗位
            pos_count = HrPosition.objects.filter(
                tenant_id=self.scope.tenant_id, organization_id=org_id, lifecycle_status="ACTIVE"
            ).count()
            if pos_count:
                add("REQUIRES_MAPPING", "ORG_HAS_POSITIONS", f"组织 {org_id} 有 {pos_count} 个在岗岗位，需岗位迁移方案")
            # 预占
            resv_count = HrPositionReservation.objects.filter(
                tenant_id=self.scope.tenant_id, status="HELD", position_id__organization_id=org_id
            ).count()
            if resv_count:
                add("WARNING", "ORG_HAS_RESERVATIONS", f"组织 {org_id} 有 {resv_count} 条岗位预占需处理")
            # HR03 正式任职事实：按本次计划生效日计算仍在有效区间内的任职。
            assignment_count = HrStaffAssignment.objects.filter(
                tenant_id=self.scope.tenant_id,
                organization_id=org_id,
                status="ACTIVE",
                effective_from__lte=case.requested_effective_date,
            ).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=case.requested_effective_date)
            ).count()
            if assignment_count:
                add(
                    "REQUIRES_MAPPING",
                    "ORG_HAS_STAFF_ASSIGNMENTS",
                    f"组织 {org_id} 在生效日有 {assignment_count} 条有效任职，需确认人员迁移方案",
                )
            else:
                add("SAFE", "ORG_HAS_NO_ACTIVE_ASSIGNMENTS", f"组织 {org_id} 在生效日无有效任职")

        return result

    @transaction.atomic
    def submit(self, case: HrStructureChangeCase):
        if case.status != HrStructureChangeCase.Status.DRAFT:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可提交")
        impact = self.impact_analysis(case)
        if impact["summary"]["blocker"]:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", "存在 BLOCKER 影响，禁止提交")
        case.items.update(validation_status="VALID")
        case.status = HrStructureChangeCase.Status.SUBMITTED
        case.impact_snapshot_json = impact
        case.save(update_fields=["status", "impact_snapshot_json"])
        return case

    @transaction.atomic
    def approve(self, case: HrStructureChangeCase):
        if case.status not in (HrStructureChangeCase.Status.SUBMITTED, HrStructureChangeCase.Status.UNDER_REVIEW):
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可批准")
        case.status = HrStructureChangeCase.Status.APPROVED
        case.approved_at = timezone.now()
        case.save(update_fields=["status", "approved_at"])
        return case

    @transaction.atomic
    def schedule(self, case: HrStructureChangeCase):
        """APPROVED → SCHEDULED（等待生效日）。"""
        if case.status != HrStructureChangeCase.Status.APPROVED:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可调度")
        case.status = HrStructureChangeCase.Status.SCHEDULED
        case.save(update_fields=["status"])
        return case

    @transaction.atomic
    def execute_effective(self, case: HrStructureChangeCase, execution_key: str) -> HrStructureChangeCase:
        """生效执行（幂等 + 真实落地）。总册 14.9。

        - select_for_update 锁 case 行，防双 runner 并发重复执行；
        - 幂等：execution_result_json.executionKey 已存在或 status=EFFECTIVE 直接返回；
        - 按 change items 落地实际动作（RENAME_ORG 建新版本等），失败置 FAILED_EFFECT 可重试。
        """
        locked = (
            HrStructureChangeCase.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=case.id)
            .first()
        )
        if locked is None:
            raise ReorgServiceError("HR02_ORG_NOT_FOUND", "变更 case 不存在", http_status=404)
        case = locked

        if case.status == HrStructureChangeCase.Status.EFFECTIVE:
            return case  # 已生效 → 幂等返回
        prev_key = (case.execution_result_json or {}).get("executionKey")
        # FAILED_EFFECT 视为可重试：同 key 时允许重新执行（先回 SCHEDULED）
        if prev_key == execution_key and case.status != HrStructureChangeCase.Status.FAILED_EFFECT:
            return case  # 同一 execution key 且非失败态已处理 → 幂等返回
        if case.status not in (HrStructureChangeCase.Status.SCHEDULED, HrStructureChangeCase.Status.FAILED_EFFECT):
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可生效")
        if case.requested_effective_date > timezone.localdate():
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", "尚未到生效日期")

        try:
            # _apply_items 内层 savepoint：失败回滚 items
            with transaction.atomic():
                self._apply_items(case)
        except Exception as exc:
            # 记录 FAILED_EFFECT（本方法外层 @transaction.atomic 会提交它），不穿透异常
            case.status = HrStructureChangeCase.Status.FAILED_EFFECT
            case.execution_result_json = {
                "executionKey": execution_key,
                "errorCode": getattr(exc, "code", "HR02_REORG_EFFECT_FAILED"),
                "error": str(exc),
            }
            case.save(update_fields=["status", "execution_result_json"])
            return case

        case.status = HrStructureChangeCase.Status.EFFECTIVE
        case.executed_at = timezone.now()
        case.execution_result_json = {"executionKey": execution_key, "effectiveAt": case.requested_effective_date.isoformat()}
        case.save(update_fields=["status", "executed_at", "execution_result_json"])
        for item in case.items.order_by("sequence"):
            if item.entity_type == "org":
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_ORGANIZATION_CHANGED,
                    payload={
                        "organizationId": str(item.entity_id),
                        "changeCaseId": str(case.id),
                        "changeType": case.change_type,
                        "actionType": item.action_type,
                        "effectiveDate": case.requested_effective_date.isoformat(),
                    },
                    correlation_id=execution_key,
                )
        emit_registered_event(
            tenant_id=self.scope.tenant_id,
            event_name=EVENT_REORGANIZATION_EFFECTIVE,
            payload={
                "changeCaseId": str(case.id),
                "caseNo": case.case_no,
                "changeType": case.change_type,
                "effectiveDate": case.requested_effective_date.isoformat(),
                "executionKey": execution_key,
            },
            correlation_id=execution_key,
        )
        return case

    @transaction.atomic
    def reset_failed_effect(self, case_id) -> HrStructureChangeCase:
        """FAILED_EFFECT → SCHEDULED 受控复位（复审 P1：提供可重试路径）。"""
        locked = (
            HrStructureChangeCase.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, id=case_id)
            .first()
        )
        if locked is None:
            raise ReorgServiceError("HR02_ORG_NOT_FOUND", "变更 case 不存在", http_status=404)
        if locked.status != HrStructureChangeCase.Status.FAILED_EFFECT:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"仅 FAILED_EFFECT 可复位，当前 {locked.status}")
        locked.status = HrStructureChangeCase.Status.SCHEDULED
        locked.save(update_fields=["status"])
        return locked

    def _locked_org_version(self, organization_id, effective_date):
        from hr_structure.models import HrOrganizationVersion

        old = (
            HrOrganizationVersion.objects.select_for_update()
            .filter(
                organization_id=organization_id,
                tenant_id=self.scope.tenant_id,
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                validity_from__lte=effective_date,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date))
            .order_by("-version_no")
            .first()
        )
        if old is None:
            raise ReorgServiceError(
                "REORG_ORG_VERSION_NOT_FOUND",
                f"组织 {organization_id} 在生效日无正式版本",
            )
        if effective_date < old.validity_from:
            raise ReorgServiceError(
                "REORG_VERSION_BOUNDARY_INVALID",
                f"生效日不得早于当前版本开始日 {old.validity_from}",
            )
        future = HrOrganizationVersion.objects.filter(
            organization_id=organization_id,
            tenant_id=self.scope.tenant_id,
            status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            validity_from__gte=effective_date,
        ).exclude(id=old.id).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=effective_date)
        ).exists()
        if future:
            raise ReorgServiceError(
                "REORG_FUTURE_VERSION_CONFLICT",
                f"组织 {organization_id} 已存在生效日之后的正式版本",
            )
        return old

    def _append_org_version(self, case, organization_id, **changes):
        from hr_structure.models import HrOrganizationVersion

        old = self._locked_org_version(
            organization_id, case.requested_effective_date
        )
        old.validity_to = case.requested_effective_date
        old.status = HrOrganizationVersion.Status.SUPERSEDED
        old.save(update_fields=["validity_to", "status"])
        values = {
            "name": old.name,
            "short_name": old.short_name,
            "org_type": old.org_type,
            "parent_organization_id_id": old.parent_organization_id_id,
            "sort_order": old.sort_order,
            "location_code": old.location_code,
            "source": old.source,
        }
        values.update(changes)
        return HrOrganizationVersion.objects.create(
            organization_id_id=organization_id,
            tenant_id=self.scope.tenant_id,
            validity_from=case.requested_effective_date,
            status=HrOrganizationVersion.Status.EFFECTIVE,
            change_case_id=case.case_no,
            version_no=old.version_no + 1,
            created_by=self.actor,
            **values,
        )

    def _replace_admin_parent_relation(self, case, organization_id, parent_id):
        from hr_structure.models import HrOrganizationRelation

        current = (
            HrOrganizationRelation.objects.select_for_update()
            .filter(
                tenant_id=self.scope.tenant_id,
                source_org_id=organization_id,
                relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                status=HrOrganizationRelation.Status.ACTIVE,
                validity_from__lte=case.requested_effective_date,
            )
            .filter(
                Q(validity_to__isnull=True)
                | Q(validity_to__gt=case.requested_effective_date)
            )
            .first()
        )
        if current:
            if case.requested_effective_date < current.validity_from:
                raise ReorgServiceError(
                    "REORG_RELATION_BOUNDARY_INVALID",
                    "新上级生效日不得早于当前关系开始日",
                )
            current.validity_to = case.requested_effective_date
            current.status = HrOrganizationRelation.Status.CLOSED
            current.save(update_fields=["validity_to", "status"])
        if parent_id:
            HrOrganizationRelation.objects.create(
                tenant_id=self.scope.tenant_id,
                source_org_id_id=organization_id,
                target_org_id_id=parent_id,
                relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                validity_from=case.requested_effective_date,
                status=HrOrganizationRelation.Status.ACTIVE,
                change_case_id=case.case_no,
                created_by=self.actor,
            )

    def _position_version(self, position, case):
        from hr_structure.models import HrPositionVersion

        current = (
            HrPositionVersion.objects.select_for_update()
            .filter(
                tenant_id=self.scope.tenant_id,
                position_id=position.id,
                validity_from__lte=case.requested_effective_date,
            )
            .filter(
                Q(validity_to__isnull=True)
                | Q(validity_to__gt=case.requested_effective_date)
            )
            .order_by("-version_no")
            .first()
        )
        if current is None:
            current = HrPositionVersion.objects.create(
                position_id=position,
                tenant_id=self.scope.tenant_id,
                organization_id_id=position.organization_id_id,
                post_catalog_version_id_id=position.post_catalog_version_id_id,
                post_grade_id_id=position.post_grade_id_id,
                position_type=position.position_type,
                planned_fte=position.planned_fte,
                max_incumbents=position.max_incumbents,
                allow_multiple_incumbents=position.allow_multiple_incumbents,
                lifecycle_status=position.lifecycle_status,
                validity_from=position.validity_from,
                validity_to=position.validity_to,
                version_no=position.version,
                change_case_id="LEGACY_BASELINE",
                reason="legacy position baseline",
                created_by=self.actor,
            )
        if case.requested_effective_date < current.validity_from:
            raise ReorgServiceError(
                "REORG_POSITION_VERSION_BOUNDARY_INVALID",
                f"生效日不得早于岗位版本开始日 {current.validity_from}",
            )
        future = HrPositionVersion.objects.filter(
            tenant_id=self.scope.tenant_id,
            position_id=position.id,
            validity_from__gte=case.requested_effective_date,
        ).exclude(id=current.id).filter(
            Q(validity_to__isnull=True)
            | Q(validity_to__gt=case.requested_effective_date)
        ).exists()
        if future:
            raise ReorgServiceError(
                "REORG_POSITION_FUTURE_VERSION_CONFLICT",
                f"岗位 {position.id} 已存在未来版本",
            )
        return current

    def _append_position_version(
        self,
        case,
        position,
        *,
        organization_id=None,
        lifecycle_status=None,
        reason="",
        **changes,
    ):
        from hr_structure.models import HrPositionVersion

        old = self._position_version(position, case)
        old.validity_to = case.requested_effective_date
        old.save(update_fields=["validity_to"])
        values = {
            "organization_id_id": organization_id or old.organization_id_id,
            "post_catalog_version_id_id": old.post_catalog_version_id_id,
            "post_grade_id_id": old.post_grade_id_id,
            "position_type": old.position_type,
            "planned_fte": old.planned_fte,
            "max_incumbents": old.max_incumbents,
            "allow_multiple_incumbents": old.allow_multiple_incumbents,
            "lifecycle_status": lifecycle_status or old.lifecycle_status,
        }
        values.update(changes)
        return HrPositionVersion.objects.create(
            position_id=position,
            tenant_id=self.scope.tenant_id,
            validity_from=case.requested_effective_date,
            version_no=old.version_no + 1,
            change_case_id=case.case_no,
            reason=reason,
            created_by=self.actor,
            **values,
        )

    def _deactivate_organization(self, case, organization):
        """Close the current version and relations without deleting history."""
        from hr_structure.models import HrOrganization, HrOrganizationRelation

        old = self._locked_org_version(
            organization.id, case.requested_effective_date
        )
        old.validity_to = case.requested_effective_date
        old.status = old.Status.SUPERSEDED
        old.save(update_fields=["validity_to", "status"])
        organization.identity_status = HrOrganization.IdentityStatus.CLOSED
        organization.closed_at = timezone.now()
        organization.save(update_fields=["identity_status", "closed_at"])
        relations = HrOrganizationRelation.objects.select_for_update().filter(
            tenant_id=self.scope.tenant_id,
            status=HrOrganizationRelation.Status.ACTIVE,
        ).filter(
            Q(source_org_id=organization.id) | Q(target_org_id=organization.id)
        ).filter(validity_from__lte=case.requested_effective_date).filter(
            Q(validity_to__isnull=True)
            | Q(validity_to__gt=case.requested_effective_date)
        )
        relations.update(
            validity_to=case.requested_effective_date,
            status=HrOrganizationRelation.Status.CLOSED,
        )

    def _reactivate_organization(self, case, organization, payload):
        from hr_structure.models import (
            HrOrganization,
            HrOrganizationRelation,
            HrOrganizationVersion,
        )

        latest = (
            HrOrganizationVersion.objects.select_for_update()
            .filter(tenant_id=self.scope.tenant_id, organization_id=organization.id)
            .order_by("-version_no")
            .first()
        )
        if latest is None:
            raise ReorgServiceError(
                "REACTIVATE_ORG_VERSION_MISSING", "组织缺少可恢复的历史版本"
            )
        if HrOrganizationVersion.objects.filter(
            tenant_id=self.scope.tenant_id,
            organization_id=organization.id,
            validity_from__lte=case.requested_effective_date,
        ).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=case.requested_effective_date)
        ).exists():
            raise ReorgServiceError(
                "REACTIVATE_ORG_VERSION_CONFLICT", "重新启用日已存在有效组织版本"
            )
        parent_id = self._payload_value(
            payload,
            "parent_organization_id",
            "parentOrganizationId",
            default=latest.parent_organization_id_id,
        )
        version = HrOrganizationVersion.objects.create(
            organization_id=organization,
            tenant_id=self.scope.tenant_id,
            name=str(self._payload_value(payload, "name", default=latest.name)).strip(),
            short_name=str(
                self._payload_value(
                    payload, "short_name", "shortName", default=latest.short_name
                )
            ).strip(),
            org_type=self._payload_value(
                payload, "org_type", "orgType", default=latest.org_type
            ),
            parent_organization_id_id=parent_id or None,
            validity_from=case.requested_effective_date,
            status=HrOrganizationVersion.Status.EFFECTIVE,
            sort_order=int(
                self._payload_value(
                    payload, "sort_order", "sortOrder", default=latest.sort_order
                )
            ),
            location_code=str(
                self._payload_value(
                    payload,
                    "location_code",
                    "locationCode",
                    default=latest.location_code,
                )
            ),
            change_case_id=case.case_no,
            version_no=latest.version_no + 1,
            source="reorganization",
            created_by=self.actor,
        )
        organization.identity_status = HrOrganization.IdentityStatus.ACTIVE
        organization.closed_at = None
        organization.save(update_fields=["identity_status", "closed_at"])
        if parent_id and organization.org_dimension == HrOrganization.Dimension.ADMIN:
            HrOrganizationRelation.objects.create(
                tenant_id=self.scope.tenant_id,
                source_org_id=organization,
                target_org_id_id=parent_id,
                relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                validity_from=case.requested_effective_date,
                status=HrOrganizationRelation.Status.ACTIVE,
                change_case_id=case.case_no,
                created_by=self.actor,
            )
        return version

    def _apply_items(self, case: HrStructureChangeCase) -> None:
        """Apply validated actions with tenant locks and effective-dated history."""
        from hr_structure.models import (
            HrHeadcountQuotaLine,
            HrOrganization,
            HrOrganizationRelation,
            HrOrganizationVersion,
            HrPosition,
            HrPositionQuotaLine,
            HrPositionVersion,
        )

        items = list(case.items.select_for_update().order_by("sequence"))
        for item in items:
            blockers = self._item_contract_blockers(
                item, case.requested_effective_date
            )
            if blockers:
                code, message = blockers[0]
                raise ReorgServiceError(code, message)

            action = item.action_type
            payload = item.after_payload or {}
            entity_id = int(item.entity_id) if item.entity_id else None

            if action == "RENAME_ORG":
                new_name = self._payload_value(payload, "name")
                if not new_name:
                    raise ReorgServiceError(
                        "RENAME_ORG_NAME_REQUIRED",
                        f"RENAME_ORG 缺少新名称 (entity={entity_id})",
                    )
                self._append_org_version(case, entity_id, name=str(new_name).strip())

            elif action == "CHANGE_ORG_TYPE":
                self._append_org_version(
                    case,
                    entity_id,
                    org_type=self._payload_value(payload, "org_type", "orgType"),
                )

            elif action == "CREATE_ORG":
                stable_code = self._payload_value(payload, "stable_code", "stableCode")
                dimension = self._payload_value(payload, "dimension", "org_dimension", "orgDimension")
                parent_id = self._payload_value(payload, "parent_organization_id", "parentOrganizationId", "parent_id", "parentId")
                org = HrOrganization.objects.create(
                    tenant_id=self.scope.tenant_id,
                    stable_code=str(stable_code).strip(),
                    org_dimension=dimension,
                    created_by=self.actor,
                )
                version = HrOrganizationVersion.objects.create(
                    organization_id=org,
                    tenant_id=self.scope.tenant_id,
                    name=str(payload["name"]).strip(),
                    short_name=str(self._payload_value(payload, "short_name", "shortName", default="") or "").strip(),
                    org_type=self._payload_value(payload, "org_type", "orgType"),
                    parent_organization_id_id=parent_id or None,
                    validity_from=case.requested_effective_date,
                    status=HrOrganizationVersion.Status.EFFECTIVE,
                    sort_order=int(self._payload_value(payload, "sort_order", "sortOrder", default=0) or 0),
                    location_code=str(self._payload_value(payload, "location_code", "locationCode", default="") or ""),
                    change_case_id=case.case_no,
                    version_no=1,
                    source="reorganization",
                    created_by=self.actor,
                )
                if parent_id and dimension == HrOrganization.Dimension.ADMIN:
                    HrOrganizationRelation.objects.create(
                        tenant_id=self.scope.tenant_id,
                        source_org_id=org,
                        target_org_id_id=parent_id,
                        relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                        validity_from=case.requested_effective_date,
                        status=HrOrganizationRelation.Status.ACTIVE,
                        change_case_id=case.case_no,
                        created_by=self.actor,
                    )
                item.entity_id = str(org.id)
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_ORGANIZATION_CREATED,
                    payload={
                        "organizationId": str(org.id),
                        "stableCode": org.stable_code,
                        "versionId": str(version.id),
                        "effectiveDate": case.requested_effective_date.isoformat(),
                    },
                    correlation_id=case.case_no,
                )

            elif action == "REPARENT_ORG":
                org = HrOrganization.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                parent_id = self._payload_value(payload, "parent_organization_id", "parentOrganizationId", "target_parent_id", "targetParentId")
                self._append_org_version(
                    case, entity_id, parent_organization_id_id=parent_id or None
                )
                if org.org_dimension == HrOrganization.Dimension.ADMIN:
                    self._replace_admin_parent_relation(case, entity_id, parent_id or None)

            elif action == "DEACTIVATE_ORG":
                organization = HrOrganization.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                self._deactivate_organization(case, organization)

            elif action == "REACTIVATE_ORG":
                organization = HrOrganization.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                self._reactivate_organization(case, organization, payload)

            elif action in {"CREATE_RELATION", "CHANGE_RELATION"}:
                relation_type = self._payload_value(
                    payload, "relation_type", "relationType"
                )
                target_id = self._payload_value(
                    payload,
                    "target_organization_id",
                    "targetOrganizationId",
                    "target_org_id",
                    "targetOrgId",
                )
                if action == "CHANGE_RELATION":
                    old_relation = HrOrganizationRelation.objects.select_for_update().get(
                        tenant_id=self.scope.tenant_id, id=entity_id
                    )
                    source_id = old_relation.source_org_id_id
                    old_relation.validity_to = case.requested_effective_date
                    old_relation.status = HrOrganizationRelation.Status.CLOSED
                    old_relation.save(update_fields=["validity_to", "status"])
                else:
                    source_id = entity_id
                new_relation = HrOrganizationRelation.objects.create(
                    tenant_id=self.scope.tenant_id,
                    source_org_id_id=source_id,
                    target_org_id_id=target_id,
                    relation_type=relation_type,
                    validity_from=case.requested_effective_date,
                    status=HrOrganizationRelation.Status.ACTIVE,
                    change_case_id=case.case_no,
                    metadata_json=self._payload_value(
                        payload, "metadata", "metadata_json", "metadataJson", default={}
                    ) or {},
                    created_by=self.actor,
                )
                if relation_type == HrOrganizationRelation.RelationType.ADMIN_PARENT:
                    source_org = HrOrganization.objects.get(
                        tenant_id=self.scope.tenant_id, id=source_id
                    )
                    if source_org.org_dimension == HrOrganization.Dimension.ADMIN:
                        self._append_org_version(
                            case,
                            source_id,
                            parent_organization_id_id=int(target_id),
                        )

            elif action == "CREATE_POSITION":
                position = HrPosition.objects.create(
                    tenant_id=self.scope.tenant_id,
                    position_code=str(self._payload_value(payload, "position_code", "positionCode")).strip(),
                    organization_id_id=self._payload_value(payload, "organization_id", "organizationId"),
                    post_catalog_version_id_id=self._payload_value(payload, "post_catalog_version_id", "postCatalogVersionId"),
                    post_grade_id_id=self._payload_value(payload, "post_grade_id", "postGradeId"),
                    position_type=self._payload_value(payload, "position_type", "positionType", default=HrPosition.PositionType.REGULAR),
                    planned_fte=self._payload_value(payload, "planned_fte", "plannedFte", default=1),
                    max_incumbents=int(self._payload_value(payload, "max_incumbents", "maxIncumbents", default=1)),
                    allow_multiple_incumbents=self._payload_bool(
                        self._payload_value(
                            payload,
                            "allow_multiple_incumbents",
                            "allowMultipleIncumbents",
                            default=False,
                        )
                    ),
                    validity_from=case.requested_effective_date,
                    lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
                    version=1,
                )
                HrPositionVersion.objects.create(
                    position_id=position,
                    tenant_id=self.scope.tenant_id,
                    organization_id_id=position.organization_id_id,
                    post_catalog_version_id_id=position.post_catalog_version_id_id,
                    post_grade_id_id=position.post_grade_id_id,
                    position_type=position.position_type,
                    planned_fte=position.planned_fte,
                    max_incumbents=position.max_incumbents,
                    allow_multiple_incumbents=position.allow_multiple_incumbents,
                    lifecycle_status=position.lifecycle_status,
                    validity_from=case.requested_effective_date,
                    version_no=1,
                    change_case_id=case.case_no,
                    reason=case.reason,
                    created_by=self.actor,
                )
                item.entity_id = str(position.id)
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_POSITION_CREATED,
                    payload={
                        "positionId": str(position.id),
                        "positionCode": position.position_code,
                        "organizationId": str(position.organization_id_id),
                        "effectiveDate": case.requested_effective_date.isoformat(),
                    },
                    correlation_id=case.case_no,
                )

            elif action == "MOVE_POSITION":
                position = HrPosition.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                target_id = self._payload_value(payload, "organization_id", "organizationId", "target_organization_id", "targetOrganizationId")
                self._append_position_version(
                    case,
                    position,
                    organization_id=target_id,
                    reason=case.reason or "MOVE_POSITION",
                )
                position.organization_id_id = target_id
                position.version += 1
                position.save(update_fields=["organization_id", "version"])
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_POSITION_STATUS_CHANGED,
                    payload={
                        "positionId": str(position.id),
                        "status": position.lifecycle_status,
                        "organizationId": str(target_id),
                        "actionType": "MOVE_POSITION",
                        "version": position.version,
                    },
                    correlation_id=case.case_no,
                )

            elif action == "CHANGE_POSITION":
                position = HrPosition.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                field_aliases = {
                    "post_catalog_version_id_id": ("post_catalog_version_id", "postCatalogVersionId"),
                    "post_grade_id_id": ("post_grade_id", "postGradeId"),
                    "position_type": ("position_type", "positionType"),
                    "planned_fte": ("planned_fte", "plannedFte"),
                    "max_incumbents": ("max_incumbents", "maxIncumbents"),
                    "allow_multiple_incumbents": ("allow_multiple_incumbents", "allowMultipleIncumbents"),
                    "lifecycle_status": ("lifecycle_status", "lifecycleStatus"),
                }
                history_changes = {}
                projection_updates = []
                for model_field, aliases in field_aliases.items():
                    sentinel = object()
                    value = self._payload_value(payload, *aliases, default=sentinel)
                    if value is sentinel:
                        continue
                    if model_field in {"post_catalog_version_id_id", "post_grade_id_id"}:
                        value = int(value) if value not in (None, "") else None
                    elif model_field == "planned_fte":
                        value = Decimal(str(value))
                    elif model_field == "max_incumbents":
                        value = int(value)
                    elif model_field == "allow_multiple_incumbents":
                        value = self._payload_bool(value)
                    history_changes[model_field] = value
                    projection_field = model_field.removesuffix("_id")
                    setattr(position, model_field, value)
                    projection_updates.append(projection_field)
                freeze_reason = self._payload_value(
                    payload, "freeze_reason", "freezeReason"
                )
                if freeze_reason is not None:
                    position.freeze_reason = str(freeze_reason)
                    projection_updates.append("freeze_reason")
                self._append_position_version(
                    case,
                    position,
                    reason=case.reason or "CHANGE_POSITION",
                    **history_changes,
                )
                position.version += 1
                projection_updates.append("version")
                position.save(update_fields=list(dict.fromkeys(projection_updates)))
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_POSITION_STATUS_CHANGED,
                    payload={
                        "positionId": str(position.id),
                        "status": position.lifecycle_status,
                        "actionType": "CHANGE_POSITION",
                        "version": position.version,
                    },
                    correlation_id=case.case_no,
                )

            elif action == "CLOSE_POSITION":
                position = HrPosition.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                reason = str(
                    self._payload_value(payload, "close_reason", "closeReason", "reason", default=case.reason)
                    or "CLOSE_POSITION"
                )
                self._append_position_version(
                    case,
                    position,
                    lifecycle_status=HrPosition.LifecycleStatus.CLOSED,
                    reason=reason,
                )
                position.lifecycle_status = HrPosition.LifecycleStatus.CLOSED
                position.validity_to = case.requested_effective_date
                position.close_reason = reason
                position.version += 1
                position.save(
                    update_fields=[
                        "lifecycle_status",
                        "validity_to",
                        "close_reason",
                        "version",
                    ]
                )
                emit_registered_event(
                    tenant_id=self.scope.tenant_id,
                    event_name=EVENT_POSITION_STATUS_CHANGED,
                    payload={
                        "positionId": str(position.id),
                        "status": position.lifecycle_status,
                        "reason": reason,
                        "version": position.version,
                    },
                    correlation_id=case.case_no,
                )

            elif action == "ADJUST_STAFFING_QUOTA":
                line = HrHeadcountQuotaLine.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                line.authorized_headcount = int(
                    self._payload_value(
                        payload, "authorized_headcount", "authorizedHeadcount"
                    )
                )
                if any(key in payload for key in ("reserve_headcount", "reserveHeadcount")):
                    line.reserve_headcount = int(
                        self._payload_value(
                            payload, "reserve_headcount", "reserveHeadcount"
                        )
                    )
                if any(key in payload for key in ("control_mode", "controlMode")):
                    line.control_mode = self._payload_value(
                        payload, "control_mode", "controlMode"
                    )
                line.version += 1
                line.save(
                    update_fields=[
                        "authorized_headcount",
                        "reserve_headcount",
                        "control_mode",
                        "version",
                    ]
                )

            elif action == "ADJUST_POSITION_QUOTA":
                line = HrPositionQuotaLine.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                line.authorized_positions = int(
                    self._payload_value(
                        payload, "authorized_positions", "authorizedPositions"
                    )
                )
                if any(key in payload for key in ("authorized_fte", "authorizedFte")):
                    line.authorized_fte = Decimal(
                        str(
                            self._payload_value(
                                payload, "authorized_fte", "authorizedFte"
                            )
                        )
                    )
                if any(key in payload for key in ("control_mode", "controlMode")):
                    line.control_mode = self._payload_value(
                        payload, "control_mode", "controlMode"
                    )
                line.save(
                    update_fields=[
                        "authorized_positions",
                        "authorized_fte",
                        "control_mode",
                    ]
                )

            elif action in {"MERGE_ORGS", "SPLIT_ORG"}:
                organization = HrOrganization.objects.select_for_update().get(
                    tenant_id=self.scope.tenant_id, id=entity_id
                )
                self._deactivate_organization(case, organization)
            else:
                raise ReorgServiceError(
                    "REORG_ACTION_UNSUPPORTED", f"action {action} 尚无安全执行合同"
                )

            item.validation_status = "VALID"
            item.execution_status = "APPLIED"
            item.save(
                update_fields=["entity_id", "validation_status", "execution_status"]
            )


def find_scheduled_cases(tenant_id, as_of=None):
    """查询到期待生效的 SCHEDULED case（effective runner 扫描）。"""
    as_of = as_of or timezone.localdate()
    return HrStructureChangeCase.objects.filter(
        tenant_id=tenant_id,
        status=HrStructureChangeCase.Status.SCHEDULED,
        requested_effective_date__lte=as_of,
    )
