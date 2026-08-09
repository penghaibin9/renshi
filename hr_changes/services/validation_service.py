"""
hr_changes/services/validation_service.py —— 案件校验服务（S3，总册 §16）。

校验等级 BLOCKER/WARNING/INFO：
- action/reason 兼容；
- 生效日期规则；
- source/target scope（跨组织调动 target 必须参与审批）；
- proposal 字段目录与必填项。
"""

from __future__ import annotations

from hr_changes.constants import CHANGE_FIELD_CATALOG, CaseStatus, ChangeActionCode, ImpactLevel
from hr_changes.models import HrPersonnelChangeCase


class ValidationService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def validate(self, case: HrPersonnelChangeCase) -> dict:
        blockers: list[dict] = []
        warnings: list[dict] = []
        infos: list[dict] = []

        # 1) 原因与动作兼容
        if case.reason_id.action_code != case.action_id.code:
            blockers.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_INVALID_REASON",
                    "message": f"原因 {case.reason_id.code} 不属于动作 {case.action_id.code}",
                    "domain": "HR06",
                }
            )

        # 2) 生效日期必填（提交后）
        if case.status not in (CaseStatus.DRAFT,) and case.requested_effective_at is None:
            blockers.append(
                {
                    "level": ImpactLevel.BLOCKER,
                    "code": "CHANGE_EFFECTIVE_DATE_INVALID",
                    "message": "提交后生效日期必填",
                    "domain": "HR06",
                }
            )

        # 3) 动作 → 必填 proposal 字段
        required_fields = _action_required_fields(case.action_id.code)
        present = {(p.domain, p.field_code) for p in case.proposals.all()}
        for domain, field_code in required_fields:
            if (domain, field_code) not in present:
                blockers.append(
                    {
                        "level": ImpactLevel.BLOCKER,
                        "code": "CHANGE_INVALID_PAYLOAD",
                        "message": f"缺少必填变更字段 {domain}.{field_code}",
                        "domain": "HR06",
                    }
                )

        # 4) 非法字段
        for p in case.proposals.all():
            catalog = CHANGE_FIELD_CATALOG.get(p.domain)
            if catalog is None or p.field_code not in catalog:
                blockers.append(
                    {
                        "level": ImpactLevel.BLOCKER,
                        "code": "CHANGE_INVALID_PAYLOAD",
                        "message": f"字段 {p.domain}.{p.field_code} 不在受管目录",
                        "domain": "HR06",
                    }
                )

        # 5) 跨组织调动：target 参与审批（WARNING 提示，S3 审批链保证）
        if case.action_id.code in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        ) and case.target_org_id_id is None:
            warnings.append(
                {
                    "level": ImpactLevel.WARNING,
                    "code": "CHANGE_TARGET_SCOPE_REQUIRED",
                    "message": "组织调动必须指定目标组织",
                    "domain": "HR06",
                }
            )

        # 6) DATA_CORRECTION 需更高级别审批（INFO）
        if case.action_id.code == ChangeActionCode.DATA_CORRECTION:
            infos.append(
                {
                    "level": ImpactLevel.INFO,
                    "code": "CORRECTION_REQUIRES_APPROVAL",
                    "message": "数据纠错将走更高权限审批（hr.change.correct）",
                    "domain": "HR06",
                }
            )

        return {
            "items": blockers + warnings + infos,
            "blockers": blockers,
            "warnings": warnings,
            "infos": infos,
        }


def _action_required_fields(action_code: str) -> list[tuple[str, str]]:
    """动作 → 必填变更字段（Proposal 校验；Change Action Matrix §4）。"""
    mapping = {
        ChangeActionCode.ORG_TRANSFER: [("assignment", "organization")],
        ChangeActionCode.POSITION_TRANSFER: [("assignment", "position")],
        ChangeActionCode.ORG_POSITION_TRANSFER: [("assignment", "organization"), ("assignment", "position")],
        ChangeActionCode.POST_CATEGORY_CHANGE: [("assignment", "post_catalog")],
        ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE: [("staff", "staff_category_code")],
        ChangeActionCode.EMPLOYMENT_TYPE_CHANGE: [("relationship", "relationship_type")],
        ChangeActionCode.MANAGER_CHANGE: [("assignment", "reporting_staff")],
        ChangeActionCode.LOCATION_CHANGE: [("assignment", "location")],
        ChangeActionCode.ADD_SECONDARY_ASSIGNMENT: [("assignment", "organization"), ("assignment", "position")],
        ChangeActionCode.END_SECONDARY_ASSIGNMENT: [("relationship", "effective_to")],
        ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH: [("assignment", "organization"), ("assignment", "position")],
        ChangeActionCode.TEMPORARY_SECONDMENT: [("temporary", "expected_return_at")],
        ChangeActionCode.TEMPORARY_ATTACHMENT: [("temporary", "expected_return_at")],
        ChangeActionCode.RETURN_FROM_TEMPORARY: [],
        ChangeActionCode.BULK_ORG_RESTRUCTURE_MOVE: [("assignment", "organization")],
        ChangeActionCode.DATA_CORRECTION: [],
    }
    return mapping.get(action_code, [])
