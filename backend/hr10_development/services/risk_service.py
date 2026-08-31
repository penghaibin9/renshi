"""
hr10_development/services/risk_service.py

风险检测服务（总册 §121/§122）。

规则扫描 → 发现 → 创建/更新 HrDevelopmentRiskCase。
仅做风险提示，不用 AI 自动判作弊。
"""

from datetime import date, datetime, timezone

from hr10_development.constants import RiskType, RiskCaseStatus, RiskSeverity


class RiskService:
    """发展风险检测与案例管理。"""

    @staticmethod
    def detect_duplicate_evidence(tenant_id: int, content_hash: str,
                                  assignment_id: int = 0) -> bool:
        """
        检测重复证据：同一文件 hash 被多个不相关 assignment 使用。

        Returns: True 若存在重复。
        """
        from hr10_development.models.practice_process import HrEnterprisePracticeEvidence
        dupes = (
            HrEnterprisePracticeEvidence.objects
            .filter(tenant_id=tenant_id, content_hash=content_hash)
            .exclude(assignment_id=assignment_id)
            .count()
        )
        return dupes > 0

    @staticmethod
    def detect_impossible_overlap(
        assignment_id: int,
        start_at,
        end_at,
    ) -> bool:
        """检测不可能的时间重叠。"""
        from hr10_development.models.practice_process import HrEnterprisePracticeActivity
        overlapping = (
            HrEnterprisePracticeActivity.objects
            .filter(
                assignment_id=assignment_id,
                status="VERIFIED",
                start_at__lt=end_at,
                end_at__gt=start_at,
            )
            .exists()
        )
        return overlapping

    @staticmethod
    def detect_future_timestamp(activity_date: date) -> bool:
        """检测未来时间戳。"""
        return activity_date > date.today()

    @staticmethod
    def open_risk_case(
        tenant_id: int,
        risk_type: str,
        severity: str = RiskSeverity.MEDIUM,
        staff_master_id: int | None = None,
        source_case_type: str = "",
        source_case_id: int | None = None,
        detected_rule_version: str = "S11_RISK_RULES_V1",
        owner_id: int | None = None,
        due_at: datetime | None = None,
    ):
        """创建风险案例（幂等：同 source_case 同类型不重复）。"""
        from hr10_development.models.development_fact import HrDevelopmentRiskCase

        existing = HrDevelopmentRiskCase.objects.filter(
            tenant_id=tenant_id,
            risk_type=risk_type,
            source_case_type=source_case_type,
            source_case_id=source_case_id,
            status__in=[RiskCaseStatus.OPEN, RiskCaseStatus.ACKNOWLEDGED, RiskCaseStatus.IN_PROGRESS],
        ).first()
        if existing:
            return existing

        return HrDevelopmentRiskCase.objects.create(
            tenant_id=tenant_id,
            risk_type=risk_type,
            staff_master_id=staff_master_id,
            source_case_type=source_case_type,
            source_case_id=source_case_id,
            severity=severity,
            status=RiskCaseStatus.OPEN,
            detected_rule_version=detected_rule_version,
            detected_at=datetime.now(timezone.utc),
            owner_id=owner_id,
            due_at=due_at,
        )

    @staticmethod
    def resolve_risk_case(risk_case, resolution_reason: str, evidence_refs: list | None = None):
        """解决风险案例。"""
        risk_case.status = RiskCaseStatus.RESOLVED
        risk_case.resolution_reason = resolution_reason
        risk_case.resolution_evidence_refs = evidence_refs or []
        risk_case.save(update_fields=["status", "resolution_reason", "resolution_evidence_refs", "updated_at"])
        return risk_case
