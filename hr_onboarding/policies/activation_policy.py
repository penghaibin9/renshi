"""
hr_onboarding/policies/activation_policy.py

Activation Gate（总册 §10.5）：正式生效前必须全部通过。
可配置追加项（合同签署/档案到校/体检/无犯罪/教师资格）由学校 policy 配置，
但下列核心项不可配置掉（§65）：tenant 隔离、来源幂等、HR02 容量、HR03 激活服务、审计、敏感控制、token 安全、版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from hr_onboarding.constants import MaterialBlockingPhase, MaterialStatus, PersonMatchStatus
from hr_onboarding.integrations.hr02 import Hr02PositionProvider
from hr_structure.selectors import effective as hr02_effective


@dataclass
class GateItem:
    code: str
    label: str
    ok: bool = False
    detail: str = ""


@dataclass
class ActivationGateResult:
    passed: bool
    items: list = field(default_factory=list)

    def add(self, code: str, label: str, ok: bool, detail: str = ""):
        self.items.append(GateItem(code=code, label=label, ok=ok, detail=detail))
        if not ok:
            self.passed = False
        return ok


def evaluate_activation_gate(
    *,
    tenant_id: int,
    case,
    effective_at: date,
    extra_policy_checks: Optional[list[dict]] = None,
) -> ActivationGateResult:
    """
    计算 Activation Gate（只读，不写库）。

    核心检查（§10.5）：
      1. 来源有效（source_type 合法且 HR04 引用存在）
      2. case 已 REPORTED
      3. Person match 已解决（EXACT/POSSIBLE 且已绑定 hr03_person_id）
      4. 激活阻断材料全部 VERIFIED/WAIVED（blocking_phase=ACTIVATION）
      5. HR02 预占有效（HELD 且未过期）
      6. 组织在 effective_at 有效（HR02 as-of）
      7. 岗位在 effective_at 有效（HR02 as-of + ACTIVE）
      8. 用工类型/人员类别已解析
      9. employment/assignment 生效日有效
    extra_policy_checks: 学校可配置追加项，每项 {"code","label","ok","detail"}。
    """
    result = ActivationGateResult(passed=True)

    # 1 来源
    result.add(
        "SOURCE_VALID",
        "入职来源有效",
        bool(case.source_type) and bool(case.source_id),
        f"source={case.source_type}",
    )

    # 2 REPORTED（REPORTED 之后 VERIFYING/READY_FOR_ACTIVATION 均视为已完成报到）
    from hr_onboarding.constants import CaseStatus

    report_ok = case.status in (
        CaseStatus.REPORTED,
        CaseStatus.VERIFYING,
        CaseStatus.READY_FOR_ACTIVATION,
        CaseStatus.ACTIVATING,
        # A failed activation does not undo the already completed report.
        # The state machine explicitly permits ACTIVATION_FAILED -> ACTIVATING
        # so retryable idempotency claims must be able to pass this gate.
        CaseStatus.ACTIVATION_FAILED,
    )
    result.add(
        "CASE_REPORTED",
        "已完成报到",
        report_ok,
        f"status={case.status}",
    )

    # 3 Person match（匹配已人工解决；激活事务内 match_or_create_person 幂等绑定）
    person_ok = case.person_match_status in (
        PersonMatchStatus.EXACT_MATCH,
        PersonMatchStatus.POSSIBLE_MATCH,
    )
    result.add(
        "PERSON_MATCH_RESOLVED",
        "Person 匹配已解决",
        person_ok,
        f"match={case.person_match_status}",
    )

    # 4 激活阻断材料（基于 requirement 而非已实例化 material：
    #    模板存在但材料未实例化 = MISSING，不得放行）
    from hr_onboarding.models import HrOnboardingMaterialRequirement, HrOnboardingMaterial

    missing_materials = 0
    if case.template_version is not None:
        blocking_reqs = HrOnboardingMaterialRequirement.objects.filter(
            tenant_id=tenant_id,
            template_version=case.template_version,
            blocking_phase=MaterialBlockingPhase.ACTIVATION,
            required=True,
        )
        for req in blocking_reqs:
            m = HrOnboardingMaterial.objects.filter(case=case, requirement=req).first()
            if m is None or m.status not in (MaterialStatus.VERIFIED, MaterialStatus.WAIVED):
                missing_materials += 1
    result.add(
        "BLOCKING_MATERIALS_OK",
        "激活阻断材料已核验",
        missing_materials == 0,
        f"missing={missing_materials}",
    )

    # 5 HR02 预占有效
    reservation_ok = True
    reservation_detail = "无预占（来源未带岗位预占）"
    if case.position_reservation_id_id:
        reservation_ok = Hr02PositionProvider(tenant_id).check_valid(
            case.position_reservation_id_id
        )
        reservation_detail = f"reservation={case.position_reservation_id_id}"
    result.add("POSITION_RESERVATION_VALID", "岗位预占有效", reservation_ok, reservation_detail)

    # 6 组织 as-of 有效。必须显式携带 tenant_id，禁止只按全局组织主键解析。
    org_ok = True
    org_detail = "无计划组织"
    if case.planned_organization_id_id:
        org_ok = (
            hr02_effective.org_version_as_of(
                tenant_id,
                case.planned_organization_id_id,
                effective_at,
            )
            is not None
        )
        org_detail = f"org={case.planned_organization_id_id}@{effective_at}"
    result.add("ORGANIZATION_ACTIVE", "组织在生效日有效", org_ok, org_detail)

    # 7 岗位 as-of 有效
    pos_ok = True
    pos_detail = "无计划岗位"
    if case.planned_position_id_id:
        pos = hr02_effective.position_as_of(case.tenant_id, case.planned_position_id_id, effective_at)
        pos_ok = pos is not None and pos.lifecycle_status == "ACTIVE"
        pos_detail = f"position={case.planned_position_id_id}@{effective_at}"
    result.add("POSITION_ACTIVE", "岗位在生效日有效", pos_ok, pos_detail)

    # 8 用工/人员类别已解析
    result.add(
        "EMPLOYMENT_TYPE_RESOLVED",
        "用工类型已解析",
        bool(case.employment_type),
    )
    result.add(
        "STAFF_CATEGORY_RESOLVED",
        "人员类别已解析",
        bool(case.staff_category),
    )

    # 9 生效日有效
    result.add(
        "EFFECTIVE_DATE_VALID",
        "生效日期有效",
        effective_at >= date(2000, 1, 1),
        f"effective_at={effective_at}",
    )

    # 可配置追加项
    for item in extra_policy_checks or []:
        result.add(
            item.get("code", "EXTRA"),
            item.get("label", "追加检查"),
            bool(item.get("ok")),
            item.get("detail", ""),
        )

    return result
