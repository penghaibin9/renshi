"""
hr10_development/services/practice_prerequisite_service.py

企业实践前置条件检查（总册 §82/§83）。

Safety / Confidentiality / IP / Agreement — 四项前置。
全部满足 → READY_TO_START；任一项缺失 → fail-closed。
"""

from enum import Enum


class PrerequisiteResult(Enum):
    PASS = "PASS"
    MISSING_SAFETY = "MISSING_SAFETY"
    MISSING_CONFIDENTIALITY = "MISSING_CONFIDENTIALITY"
    MISSING_IP = "MISSING_IP"
    MISSING_AGREEMENT = "MISSING_AGREEMENT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class PracticePrerequisiteService:
    """
    企业实践前置条件检查。

    检查：
    1. 安全培训与 PPE（safety_ack_ref）
    2. 保密协议（confidentiality_ack_ref）
    3. IP 声明
    4. 实践协议（approved_by_enterprise + approved_by_school）

    全部 PASS → READY_TO_START 可用。
    任一项 FAIL → fail-closed，不自动通过。
    """

    @staticmethod
    def check_all(plan) -> PrerequisiteResult:
        """
        检查实践计划的所有前置条件。

        Args:
            plan: HrEnterprisePracticePlan 实例

        Returns:
            PrerequisiteResult: PASS 或第一个失败项
        """
        # 1. 安全前置
        if not plan.safety_ack_ref:
            return PrerequisiteResult.MISSING_SAFETY

        # 2. 保密前置
        if not plan.confidentiality_ack_ref:
            return PrerequisiteResult.MISSING_CONFIDENTIALITY

        # 3. IP 前置（通过项目版本的 confidentiality_ip_requirements_json 判断）
        #    S10 阶段：如有要求则检查是否存在 IP acknowledgment
        from hr10_development.models.practice_project import HrEnterprisePracticeProjectVersion
        try:
            version = HrEnterprisePracticeProjectVersion.objects.get(
                id=plan.assignment.placement.project_version_id
            )
            ip_req = version.confidentiality_ip_requirements_json or {}
            if ip_req.get("ip_acknowledgment_required"):
                # IP acknowledgment 存储在同字段中
                if "IP_ACK" not in (plan.confidentiality_ack_ref or ""):
                    return PrerequisiteResult.MISSING_IP
        except Exception:
            return PrerequisiteResult.SOURCE_UNAVAILABLE

        # 4. 双方审批
        if not plan.approved_by_enterprise or not plan.approved_by_school:
            return PrerequisiteResult.MISSING_AGREEMENT

        return PrerequisiteResult.PASS

    @staticmethod
    def is_ready_to_start(plan) -> bool:
        """检查是否可以进入 READY_TO_START 状态。"""
        return PracticePrerequisiteService.check_all(plan) == PrerequisiteResult.PASS
