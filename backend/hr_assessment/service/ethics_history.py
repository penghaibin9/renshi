"""HR12 — S8 师德 Gate 服务 + S9 self history 服务。"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from hr_assessment.models.case import HrAssessmentCase, HrEthicsAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult


class EthicsGateService:
    """师德门槛评估 — 总册 §140。

    只引用正式已生效事实（EthicsFactProvider），不根据未核实投诉/舆情/AI 判定。
    """

    def evaluate(self, case: HrEthicsAssessmentCase) -> Dict[str, Any]:
        """返回 gate 评估结果。"""
        if case.gate_status == "BLOCKED_BY_FORMAL_FACT":
            return {
                "status": "BLOCKED",
                "reason": case.gate_reason_code or "正式师德事实阻断",
                "source_refs": case.source_refs_json,
                "can_override_by_authorized_body": True,
            }
        if case.gate_status == "REVIEW_REQUIRED":
            return {"status": "REVIEW_REQUIRED", "reason": "需人工审定", "source_refs": []}
        if case.gate_status == "UNAVAILABLE":
            return {"status": "UNAVAILABLE", "reason": "师德事实源不可用 — 需人工审定", "source_refs": []}
        return {"status": "PASS", "reason": "师德评价通过", "source_refs": []}

    def hard_gate_result(self, case: HrEthicsAssessmentCase) -> str:
        result = self.evaluate(case)
        return result["status"]


class SelfHistoryService:
    """本人考核历史查询 — 总册 §173/personal history。"""

    def get_personal_timeline(self, tenant_id: int, staff_id: uuid.UUID) -> list:
        # FinalResult 只保存 case_id，因此先从所有考核 Case（年度/聘期/专项/师德）
        # 解析本人 case 集。两层查询都必须显式限定 tenant，禁止返回全校甚至跨校结果。
        case_ids = HrAssessmentCase.objects.filter(
            tenant_id=tenant_id,
            staff_id=staff_id,
        ).values_list("id", flat=True)
        final_results = (
            HrFinalAssessmentResult.objects.filter(
                tenant_id=tenant_id,
                case_id__in=case_ids,
            )
            .order_by("-finalized_at")[:50]
        )
        return [
            {
                "case_id": str(r.case_id),
                "assessment_type": r.assessment_type,
                "grade_code": r.grade_code,
                "result_version_no": r.result_version_no,
                "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
                "status": r.status,
            }
            for r in final_results
        ]
