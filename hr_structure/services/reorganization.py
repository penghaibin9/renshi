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
        """生效执行（幂等）。总册 14.9：明确 scheduler/worker、幂等 key、事务、失败可重试。"""
        if execution_key != getattr(case, "_execution_key", execution_key) or case.status == HrStructureChangeCase.Status.EFFECTIVE:
            return case  # 幂等：已生效直接返回
        if case.status != HrStructureChangeCase.Status.SCHEDULED:
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", f"当前状态 {case.status} 不可生效")
        # 到生效日才允许
        if case.requested_effective_date > date.today():
            raise ReorgServiceError("HR02_REORG_HAS_BLOCKERS", "尚未到生效日期")
        case.status = HrStructureChangeCase.Status.EFFECTIVE
        case.executed_at = timezone.now()
        case.execution_result_json = {"executionKey": execution_key, "effectiveAt": case.requested_effective_date.isoformat()}
        case.save(update_fields=["status", "executed_at", "execution_result_json"])
        return case


def find_scheduled_cases(tenant_id, as_of=None):
    """查询到期待生效的 SCHEDULED case（effective runner 扫描）。"""
    as_of = as_of or date.today()
    return HrStructureChangeCase.objects.filter(
        tenant_id=tenant_id,
        status=HrStructureChangeCase.Status.SCHEDULED,
        requested_effective_date__lte=as_of,
    )
