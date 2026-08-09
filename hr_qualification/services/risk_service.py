"""
hr_qualification/services/risk_service.py —— 风险检测服务（总册 §33/§91-93/§130）。

- 风险检测规则：缺少必需证书、证书未核验、即将到期、已到期、已撤销、证据失效
- 风险去重（同 person + 同 type + OPEN → 不重复创建）
- Take Action：核验/续证/启动复核/补材料/关闭误报
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from hr_qualification.constants import CredentialStatus, RiskSeverity, RiskStatus, RiskType
from hr_qualification.models import (
    HrPersonCredential,
    HrQualificationRiskCase,
)


class RiskService:
    """风险检测与管理服务。"""

    # ---- 检测规则 ----

    @staticmethod
    def detect_expiring_credentials(
        tenant_id: int,
        days_threshold: int = 90,
    ) -> list[HrQualificationRiskCase]:
        """检测即将到期的证书，自动开 RiskCase。"""
        threshold_date = date.today() + timedelta(days=days_threshold)
        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            status=CredentialStatus.ACTIVE,
            valid_to__isnull=False,
            valid_to__lte=threshold_date,
            valid_to__gte=date.today(),
        )

        cases: list[HrQualificationRiskCase] = []
        for c in credentials:
            case = RiskService._upsert_risk(
                tenant_id=c.tenant_id,
                person_id=c.person_id,
                credential_id=c.id,
                risk_type=RiskType.CREDENTIAL_EXPIRING,
                severity=RiskSeverity.MEDIUM,
                due_at=c.valid_to,
            )
            if case:
                cases.append(case)
        return cases

    @staticmethod
    def detect_expired_credentials(
        tenant_id: int,
    ) -> list[HrQualificationRiskCase]:
        """检测已到期证书。"""
        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            status=CredentialStatus.ACTIVE,
            valid_to__isnull=False,
            valid_to__lt=date.today(),
        )

        cases: list[HrQualificationRiskCase] = []
        for c in credentials:
            case = RiskService._upsert_risk(
                tenant_id=c.tenant_id,
                person_id=c.person_id,
                credential_id=c.id,
                risk_type=RiskType.CREDENTIAL_EXPIRED,
                severity=RiskSeverity.HIGH,
            )
            if case:
                cases.append(case)
        return cases

    @staticmethod
    def detect_revoked_credentials(
        tenant_id: int,
    ) -> list[HrQualificationRiskCase]:
        """检测被撤销的证书（CRITICAL）。"""
        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            status=CredentialStatus.REVOKED,
        )

        cases: list[HrQualificationRiskCase] = []
        for c in credentials:
            case = RiskService._upsert_risk(
                tenant_id=c.tenant_id,
                person_id=c.person_id,
                credential_id=c.id,
                risk_type=RiskType.CREDENTIAL_REVOKED,
                severity=RiskSeverity.CRITICAL,
            )
            if case:
                cases.append(case)
        return cases

    # ---- 风险管理 ----

    @staticmethod
    def acknowledge(risk_id: uuid.UUID) -> HrQualificationRiskCase:
        case = HrQualificationRiskCase.objects.get(id=risk_id)
        case.status = RiskStatus.ACKNOWLEDGED
        case.save()
        return case

    @staticmethod
    def resolve(
        risk_id: uuid.UUID,
        resolution: str = "",
    ) -> HrQualificationRiskCase:
        case = HrQualificationRiskCase.objects.get(id=risk_id)
        case.status = RiskStatus.RESOLVED
        case.resolution = resolution
        case.resolved_at = datetime.now()
        case.save()
        return case

    @staticmethod
    def dismiss(risk_id: uuid.UUID, reason: str = "False alarm") -> HrQualificationRiskCase:
        case = HrQualificationRiskCase.objects.get(id=risk_id)
        case.status = RiskStatus.DISMISSED
        case.resolution = reason
        case.save()
        return case

    # ---- 内部 ----

    @staticmethod
    def _upsert_risk(
        tenant_id: int,
        person_id,
        credential_id: uuid.UUID,
        risk_type: str,
        severity: str,
        due_at: date | None = None,
    ) -> HrQualificationRiskCase | None:
        """去重创建 RiskCase。"""
        existing = HrQualificationRiskCase.objects.filter(
            tenant_id=tenant_id,
            person_id=person_id,
            credential_id=credential_id,
            risk_type=risk_type,
            status=RiskStatus.OPEN,
        ).first()

        if existing:
            return None  # 已存在 OPEN 状态，不重复

        return HrQualificationRiskCase.objects.create(
            tenant_id=tenant_id,
            person_id=person_id,
            credential_id=credential_id,
            risk_type=risk_type,
            severity=severity,
            due_at=due_at,
            status=RiskStatus.OPEN,
        )
