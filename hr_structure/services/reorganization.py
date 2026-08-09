"""
hr_structure/services/reorganization.py

ReorganizationService —— 组织历史与重组（总册 14 节）。

- case 状态机：DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → SCHEDULED → EFFECTIVE
- 影响分析（50.7 依赖矩阵）：下级组织/岗位/预占/HR03 任职(占位)/招聘(占位)/权限(占位)
- effective runner：到期生效（幂等 execution key）
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

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

    def impact_analysis(self, case: HrStructureChangeCase) -> dict:
        """影响分析（总册 14.8 / 50.7 依赖矩阵）。

        返回 BLOCKER / REQUIRES_MAPPING / WARNING / SAFE 分类。
        HR03 任职、招聘、合同等下游尚未接入 → 用契约占位。
        """
        from hr_structure.models import HrOrganization, HrOrganizationVersion, HrPosition, HrPositionReservation

        items = list(case.items.all())
        org_ids = set()
        for item in items:
            if item.entity_type == "org":
                org_ids.add(int(item.entity_id))

        result = {"summary": {"blocker": 0, "requiresMapping": 0, "warning": 0, "safe": 0}, "checks": []}

        def add(level, code, message):
            key = "requiresMapping" if level == "REQUIRES_MAPPING" else level.lower()
            result["summary"][key] += 1
            result["checks"].append({"level": level, "code": code, "message": message})

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
            # HR03 任职（占位：待 HR03 交付后接入真实 assignment）
            # [总控占位] 待 HR03 任职事实层交付后替换为真实 assignment 查询
            add("SAFE", "HR03_ASSIGNMENT_PENDING", f"组织 {org_id} 人员任职影响待 HR03 交付后接入")

        return result

    @transaction.atomic
    def submit(self, case: HrStructureChangeCase):
        if case.status != HrStructureChangeCase.Status.DRAFT:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可提交")
        impact = self.impact_analysis(case)
        if impact["summary"]["blocker"]:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", "存在 BLOCKER 影响，禁止提交")
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
            case.execution_result_json = {"executionKey": execution_key, "error": str(exc)}
            case.save(update_fields=["status", "execution_result_json"])
            return case

        case.status = HrStructureChangeCase.Status.EFFECTIVE
        case.executed_at = timezone.now()
        case.execution_result_json = {"executionKey": execution_key, "effectiveAt": case.requested_effective_date.isoformat()}
        case.save(update_fields=["status", "executed_at", "execution_result_json"])
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

    def _apply_items(self, case: HrStructureChangeCase) -> None:
        """按 change items 落地实际动作。当前支持 RENAME_ORG（建新版本，历史不漂移）。"""
        from datetime import date as _date

        from hr_structure.models import HrOrganizationVersion

        items = list(case.items.order_by("sequence"))
        for item in items:
            action = item.action_type
            entity_id = int(item.entity_id) if item.entity_id else None
            if action == "RENAME_ORG" and entity_id:
                new_name = (item.after_payload or {}).get("name")
                if not new_name:
                    raise ValueError(f"RENAME_ORG 缺少新名称 (entity={entity_id})")
                # 关闭旧版本，建新版本（生效日为新版本 validity_from）
                # 锁当前版本行，防并发 case 同时改同一 org（复审 P1）
                old = (
                    HrOrganizationVersion.objects.select_for_update()
                    .filter(
                        organization_id=entity_id,
                        tenant_id=self.scope.tenant_id,
                        status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                        validity_to__isnull=True,
                    )
                    .order_by("-version_no")
                    .first()
                )
                if old is None:
                    raise ValueError(f"组织 {entity_id} 无当前有效版本")
                if case.requested_effective_date < old.validity_from:
                    raise ValueError(
                        f"生效日 {case.requested_effective_date} 早于当前版本开始日 {old.validity_from}（INV-04 重叠）"
                    )
                # 校验已存在未来版本（APPROVED 且 validity_from >= 生效日）不重叠（INV-04/INV-13）
                future_conflict = HrOrganizationVersion.objects.filter(
                    organization_id=entity_id,
                    tenant_id=self.scope.tenant_id,
                    status__in=("APPROVED", "EFFECTIVE"),
                    validity_from__gte=case.requested_effective_date,
                    validity_to__isnull=True,
                ).exclude(id=old.id).exists()
                if future_conflict:
                    raise ValueError(f"组织 {entity_id} 存在与生效日重叠的未来版本")
                old.validity_to = case.requested_effective_date
                old.status = HrOrganizationVersion.Status.SUPERSEDED
                old.save(update_fields=["validity_to", "status"])
                HrOrganizationVersion.objects.create(
                    organization_id_id=entity_id,
                    tenant_id=self.scope.tenant_id,
                    name=new_name,
                    short_name=old.short_name,
                    org_type=old.org_type,
                    parent_organization_id_id=old.parent_organization_id_id,
                    validity_from=case.requested_effective_date,
                    status=HrOrganizationVersion.Status.EFFECTIVE,
                    sort_order=old.sort_order,
                    change_case_id=case.case_no,
                    version_no=old.version_no + 1,
                    created_by=self.actor,
                )
            # 其他 action_type（CREATE_ORG/MERGE/SPLIT/REPARENT/MOVE_POSITION 等）
            # 当前为最小实现：记录未执行，避免静默假生效。
            elif action in ("CREATE_ORG", "MERGE_ORGS", "SPLIT_ORG", "REPARENT_ORG", "MOVE_POSITION", "CREATE_POSITION", "CLOSE_POSITION"):
                raise ValueError(f"action {action} 暂未实现落地，拒绝假生效")


def find_scheduled_cases(tenant_id, as_of=None):
    """查询到期待生效的 SCHEDULED case（effective runner 扫描）。"""
    as_of = as_of or date.today()
    return HrStructureChangeCase.objects.filter(
        tenant_id=tenant_id,
        status=HrStructureChangeCase.Status.SCHEDULED,
        requested_effective_date__lte=as_of,
    )
