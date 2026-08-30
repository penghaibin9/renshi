"""
hr_changes/services/impact_service.py —— 影响分析服务（S3，总册 §15/§16）。

异动提交/审批前必须 Preview：
- BLOCKER 不能普通用户忽略（特权 override 需 audit；tenant/物理容量/非法状态绝不允许 override）；
- WARNING 可展开；INFO 提示。
- 每次计算保存 HrChangeImpactSnapshot（版本化，审批重检依据）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from hr_changes.constants import ChangeActionCode, ImpactLevel
from hr_changes.models import HrChangeImpactSnapshot, HrPersonnelChangeCase
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class _Item(dict):
    """影响项：{level, code, message, domain, actionable}。"""


class ImpactProvider:
    name = "base"

    def compute(self, case: HrPersonnelChangeCase, as_of: date) -> list[dict]:
        return []


# ---------------------------------------------------------------------------
# HR06：生效能力 gate。没有 Authority 写入口的动作禁止进入“可生效”链。
# ---------------------------------------------------------------------------
class Hr06ApplySupportProvider(ImpactProvider):
    name = "HR06-APPLY-SUPPORT"

    # 这些动作已经出现在合同/影响分析中，但当前 ApplyService._apply_domain
    # 尚无对应 Authority fact writer。若不阻断，会出现“0 事实写入却 EFFECTIVE”。
    _UNSUPPORTED = frozenset(
        {
            ChangeActionCode.POST_CATEGORY_CHANGE,
            ChangeActionCode.LOCATION_CHANGE,
            ChangeActionCode.BULK_ORG_RESTRUCTURE_MOVE,
            ChangeActionCode.DATA_CORRECTION,
        }
    )

    def compute(self, case, as_of):
        action = case.action_id.code
        if action not in self._UNSUPPORTED:
            return []
        return [
            {
                "level": ImpactLevel.BLOCKER,
                "code": "CHANGE_INVALID_ACTION",
                "message": f"异动动作 {action} 尚未接入 Authority 生效写入口，禁止标记已生效",
                "domain": "HR06",
                "actionable": "先完成对应领域写入服务，再开放生效",
            }
        ]


# ---------------------------------------------------------------------------
# HR02：目标岗位容量（BLOCKER 级，禁止 override）
# ---------------------------------------------------------------------------
class Hr02PositionCapacityProvider(ImpactProvider):
    name = "HR02"

    def compute(self, case, as_of):
        items = []
        target_position = case.target_position_id
        if target_position is None:
            return items
        if target_position.lifecycle_status != "ACTIVE":
            items.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_TARGET_POSITION_INVALID",
                    "message": "目标岗位未激活或已关闭",
                    "domain": "HR02",
                    "actionable": "选择有效岗位",
                }
            )
            return items
        occupancy = EffectiveDatedQueryService(case.tenant_id).position_occupancy_as_of(
            target_position.id, as_of
        )
        if occupancy >= target_position.max_incumbents:
            items.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_POSITION_CAPACITY_CONFLICT",
                    "message": f"目标岗位可用额度不足（已占 {occupancy}/{target_position.max_incumbents}）",
                    "domain": "HR02",
                    "actionable": "扩容岗位或选择其他岗位",
                }
            )
        return items


class Hr02TargetOrgProvider(ImpactProvider):
    """目标组织有效性（BLOCKER）。"""

    name = "HR02-ORG"

    def compute(self, case, as_of):
        target_org = case.target_org_id
        if target_org is None:
            return []
        if target_org.identity_status != "ACTIVE":
            return [
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_TARGET_ORG_INVALID",
                    "message": "目标组织已停用",
                    "domain": "HR02",
                    "actionable": "选择有效组织",
                }
            ]
        return []


# ---------------------------------------------------------------------------
# HR03：当前事实快照 + 人员状态（离职/待离职不得生效未来调动 = BLOCKER）
# ---------------------------------------------------------------------------
class Hr03FactsProvider(ImpactProvider):
    name = "HR03"

    def compute(self, case, as_of):
        items = []
        qs = EffectiveDatedQueryService(case.tenant_id)
        status = qs.status_as_of(case.staff_master_id_id, as_of)
        if status in ("DEPARTED", "DEPARTURE_PENDING", "RETIRED"):
            items.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                    "message": f"人员当前状态为「{status}」，不允许发起异动",
                    "domain": "HR03",
                    "actionable": "确认人员在职状态",
                }
            )
        primary = qs.primary_assignment_as_of(case.staff_master_id_id, as_of)
        if case.action_id.code == ChangeActionCode.END_SECONDARY_ASSIGNMENT:
            source_is_current_concurrent = (
                case.source_assignment_id_id is not None
                and qs.assignments_as_of(case.staff_master_id_id, as_of)
                .filter(
                    id=case.source_assignment_id_id,
                    assignment_type="CONCURRENT",
                )
                .exists()
            )
            if not source_is_current_concurrent:
                items.append(
                    {
                        "level": ImpactLevel.BLOCKER,
                        "code": "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                        "message": "取消兼岗必须选择该人员当前生效中的兼岗",
                        "domain": "HR03",
                        "actionable": "从 HR03 当前兼岗列表重新选择",
                    }
                )
        elif (
            case.source_assignment_id_id
            and primary
            and str(case.source_assignment_id_id) != str(primary.id)
        ):
            items.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                    "message": "案件主岗与人员当前主岗不一致",
                    "domain": "HR03",
                    "actionable": "核对主岗后重试",
                }
            )
        return items


# ---------------------------------------------------------------------------
# 下游 WARNING Provider（不自建权威事实，只提示）
# ---------------------------------------------------------------------------
class Hr07ContractProvider(ImpactProvider):
    """用工性质/合同条款变化 → HR07 复核请求。"""

    name = "HR07"

    def compute(self, case, as_of):
        if case.action_id.code in (
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        ):
            return [
                {
                    "level": ImpactLevel.WARNING,
                    "code": "CONTRACT_REVIEW_REQUIRED",
                    "message": "合同条款可能需要复核（将向 HR07 发起 ContractReviewRequired）",
                    "domain": "HR07",
                }
            ]
        return []


class Hr11AttendanceProvider(ImpactProvider):
    name = "HR11"

    def compute(self, case, as_of):
        if case.action_id.code in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
            ChangeActionCode.POST_CATEGORY_CHANGE,
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
        ):
            return [
                {
                    "level": ImpactLevel.WARNING,
                    "code": "ATTENDANCE_RULE_DIFF",
                    "message": "考勤规则可能变化（将发起 AttendanceRuleReevaluationRequested）",
                    "domain": "HR11",
                }
            ]
        return []


class Hr15CompensationProvider(ImpactProvider):
    name = "HR15"

    def compute(self, case, as_of):
        if case.action_id.code in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
            ChangeActionCode.POST_CATEGORY_CHANGE,
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
        ):
            return [
                {
                    "level": ImpactLevel.WARNING,
                    "code": "COMPENSATION_RECALC_REQUIRED",
                    "message": "薪酬可能需要重新测算（将发起 CompensationRecalculationRequested）",
                    "domain": "HR15",
                }
            ]
        return []


class Hr14AppointmentProvider(ImpactProvider):
    """岗位类别变化不与 HR14 聘任混淆（INFO 提示）。"""

    name = "HR14"

    def compute(self, case, as_of):
        if case.action_id.code == ChangeActionCode.POST_CATEGORY_CHANGE:
            return [
                {
                    "level": ImpactLevel.INFO,
                    "code": "POST_CATEGORY_NOT_APPOINTMENT",
                    "message": "岗位类别变更不影响 HR14 专业技术岗位聘任等级",
                    "domain": "HR14",
                }
            ]
        return []


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
IMPACT_PROVIDERS = [
    Hr06ApplySupportProvider(),
    Hr02PositionCapacityProvider(),
    Hr02TargetOrgProvider(),
    Hr03FactsProvider(),
    Hr07ContractProvider(),
    Hr11AttendanceProvider(),
    Hr15CompensationProvider(),
    Hr14AppointmentProvider(),
]


class ImpactService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def compute(self, case: HrPersonnelChangeCase, as_of: Optional[date] = None) -> dict:
        """计算全部影响并保存快照。返回 {items, blockers, warnings}。"""
        as_of = as_of or timezone.localdate()
        items: list[dict] = []
        for provider in IMPACT_PROVIDERS:
            items.extend(provider.compute(case, as_of))

        blockers = [i for i in items if i["level"] == ImpactLevel.BLOCKER]
        warnings = [i for i in items if i["level"] == ImpactLevel.WARNING]
        infos = [i for i in items if i["level"] == ImpactLevel.INFO]

        snapshot = HrChangeImpactSnapshot(
            change_case_id=case,
            impacts_json=items,
            blockers_json=blockers,
            warnings_json=warnings,
        )
        # 幂等版本化：同一 case 每次重算新版本
        latest = (
            HrChangeImpactSnapshot.objects.filter(change_case_id=case)
            .order_by("-snapshot_version")
            .first()
        )
        snapshot.snapshot_version = (latest.snapshot_version + 1) if latest else 1
        snapshot.save()

        return {"items": items, "blockers": blockers, "warnings": warnings, "infos": infos}

    def check_blockers(
        self, case: HrPersonnelChangeCase, as_of: Optional[date] = None
    ) -> list[dict]:
        return self.compute(case, as_of=as_of)["blockers"]
