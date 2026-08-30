"""
hr_structure/services/reorganization.py

ReorganizationService —— 组织历史与重组（总册 14 节）。

- case 状态机：DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → SCHEDULED → EFFECTIVE
- 影响分析（50.7 依赖矩阵）：下级组织/岗位/预占/HR03 任职(占位)/招聘(占位)/权限(占位)
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
    EVENT_ORGANIZATION_CREATED,
    EVENT_ORGANIZATION_CHANGED,
    EVENT_POSITION_CREATED,
    EVENT_POSITION_STATUS_CHANGED,
    EVENT_REORGANIZATION_EFFECTIVE,
)

from hr_structure.models import HrStructureChangeCase, HrStructureChangeItem
from hr_structure.scope import Hr02Scope


class ReorgServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
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

    def _item_contract_blockers(self, item, effective_date) -> list[tuple[str, str]]:
        """Return stable blockers before a case can leave DRAFT.

        The execution runner re-runs these checks to protect approved cases from
        item tampering between approval and the effective date.
        """
        from hr_staff.models import HrStaffAssignment
        from hr_structure.models import (
            HrOrganization,
            HrOrganizationVersion,
            HrPosition,
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

        def position(position_id):
            pos = HrPosition.objects.filter(
                tenant_id=self.scope.tenant_id, id=position_id
            ).first()
            if pos is None:
                blockers.append(("REORG_POSITION_NOT_FOUND", f"岗位 {position_id} 不存在或跨租户"))
            return pos

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
                if int(
                    self._payload_value(
                        payload, "max_incumbents", "maxIncumbents", default=1
                    )
                ) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                blockers.append(("CREATE_POSITION_CAPACITY_INVALID", "max_incumbents 必须是正整数"))

        elif action in {"MOVE_POSITION", "CLOSE_POSITION"}:
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
            if pos:
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

        elif action in {"MERGE_ORGS", "SPLIT_ORG"}:
            blockers.append((
                "REORG_MAPPING_CONTRACT_UNAVAILABLE",
                f"{action} 需要子组织、岗位、编制、HR03 任职、权限及未决业务的可执行映射；当前模型不能安全推断",
            ))
        else:
            blockers.append(("REORG_ACTION_UNSUPPORTED", f"action {action} 尚无安全执行合同"))
        return blockers

    def impact_analysis(self, case: HrStructureChangeCase) -> dict:
        """影响分析（总册 14.8 / 50.7 依赖矩阵）。

        返回 BLOCKER / REQUIRES_MAPPING / WARNING / SAFE 分类。
        HR03 任职使用正式任职事实按计划生效日计算；其他下游保持显式契约边界。
        """
        from hr_staff.models import HrStaffAssignment
        from hr_structure.models import HrOrganizationVersion, HrPosition, HrPositionReservation

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
        if case.requested_effective_date > date.today():
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
        ).exclude(id=old.id).exists()
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
        ).exclude(id=current.id).exists()
        if future:
            raise ReorgServiceError(
                "REORG_POSITION_FUTURE_VERSION_CONFLICT",
                f"岗位 {position.id} 已存在未来版本",
            )
        return current

    def _append_position_version(
        self, case, position, *, organization_id=None, lifecycle_status=None, reason=""
    ):
        from hr_structure.models import HrPositionVersion

        old = self._position_version(position, case)
        old.validity_to = case.requested_effective_date
        old.save(update_fields=["validity_to"])
        return HrPositionVersion.objects.create(
            position_id=position,
            tenant_id=self.scope.tenant_id,
            organization_id_id=organization_id or old.organization_id_id,
            post_catalog_version_id_id=old.post_catalog_version_id_id,
            post_grade_id_id=old.post_grade_id_id,
            position_type=old.position_type,
            planned_fte=old.planned_fte,
            max_incumbents=old.max_incumbents,
            allow_multiple_incumbents=old.allow_multiple_incumbents,
            lifecycle_status=lifecycle_status or old.lifecycle_status,
            validity_from=case.requested_effective_date,
            version_no=old.version_no + 1,
            change_case_id=case.case_no,
            reason=reason,
            created_by=self.actor,
        )

    def _apply_items(self, case: HrStructureChangeCase) -> None:
        """Apply validated actions with tenant locks and effective-dated history."""
        from hr_structure.models import (
            HrOrganization,
            HrOrganizationRelation,
            HrOrganizationVersion,
            HrPosition,
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
                    allow_multiple_incumbents=bool(self._payload_value(payload, "allow_multiple_incumbents", "allowMultipleIncumbents", default=False)),
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
    as_of = as_of or date.today()
    return HrStructureChangeCase.objects.filter(
        tenant_id=tenant_id,
        status=HrStructureChangeCase.Status.SCHEDULED,
        requested_effective_date__lte=as_of,
    )
