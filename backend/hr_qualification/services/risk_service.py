"""
hr_qualification/services/risk_service.py —— 风险检测服务（总册 §33/§91-93/§130）。

- 风险检测规则：缺少必需证书、证书未核验、即将到期、已到期、已撤销、证据失效
- 风险去重（同 person + 同 type + OPEN → 不重复创建）
- Take Action：核验/续证/启动复核/补材料/关闭误报
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from hr_qualification.constants import CredentialStatus, RiskSeverity, RiskStatus, RiskType
from hr_qualification.models import (
    HrPersonCredential,
    HrQualificationRiskCase,
)
from hr_staff.models import HrPerson


class RiskError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class RiskService:
    """风险检测与管理服务。"""

    # ---- 检测规则 ----

    @staticmethod
    def detect_expiring_credentials(
        tenant_id: int,
        days_threshold: int = 90,
    ) -> list[HrQualificationRiskCase]:
        """检测即将到期的证书，自动开 RiskCase。"""
        today = timezone.localdate()
        threshold_date = today + timedelta(days=days_threshold)
        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            status=CredentialStatus.ACTIVE,
            valid_to__isnull=False,
            valid_to__lte=threshold_date,
            valid_to__gte=today,
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
        today = timezone.localdate()
        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            status=CredentialStatus.ACTIVE,
            valid_to__isnull=False,
            valid_to__lt=today,
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
    @transaction.atomic
    def acknowledge(risk_id: uuid.UUID) -> HrQualificationRiskCase:
        case = HrQualificationRiskCase.objects.select_for_update().get(id=risk_id)
        if case.status == RiskStatus.ACKNOWLEDGED:
            return case
        if case.status != RiskStatus.OPEN:
            raise RiskError(
                "RISK_INVALID_STATE",
                f"risk is {case.status}, cannot acknowledge",
            )
        case.status = RiskStatus.ACKNOWLEDGED
        case.version += 1
        case.save(update_fields=["status", "version", "updated_at"])
        return case

    @staticmethod
    @transaction.atomic
    def resolve(
        risk_id: uuid.UUID,
        resolution: str = "",
        resolved_by: int | None = None,
    ) -> HrQualificationRiskCase:
        resolution = str(resolution or "").strip()
        if not resolution:
            raise RiskError("RISK_RESOLUTION_REQUIRED", "resolution is required")
        case = HrQualificationRiskCase.objects.select_for_update().get(id=risk_id)
        if case.status == RiskStatus.RESOLVED:
            if case.resolution == resolution:
                return case
            raise RiskError(
                "RISK_RESOLUTION_CONFLICT",
                "risk has already been resolved with a different resolution",
            )
        if case.status not in {
            RiskStatus.OPEN,
            RiskStatus.ACKNOWLEDGED,
            RiskStatus.IN_PROGRESS,
        }:
            raise RiskError(
                "RISK_INVALID_STATE",
                f"risk is {case.status}, cannot resolve",
            )
        case.status = RiskStatus.RESOLVED
        case.resolution = resolution
        case.resolved_at = timezone.now()
        case.resolved_by = resolved_by
        case.version += 1
        case.save(
            update_fields=[
                "status",
                "resolution",
                "resolved_at",
                "resolved_by",
                "version",
                "updated_at",
            ]
        )
        return case

    @staticmethod
    @transaction.atomic
    def dismiss(risk_id: uuid.UUID, reason: str = "False alarm") -> HrQualificationRiskCase:
        reason = str(reason or "").strip()
        if not reason:
            raise RiskError("RISK_DISMISSAL_REASON_REQUIRED", "dismissal reason is required")
        case = HrQualificationRiskCase.objects.select_for_update().get(id=risk_id)
        if case.status == RiskStatus.DISMISSED:
            if case.resolution == reason:
                return case
            raise RiskError(
                "RISK_DISMISSAL_CONFLICT",
                "risk has already been dismissed with a different reason",
            )
        if case.status not in {RiskStatus.OPEN, RiskStatus.ACKNOWLEDGED}:
            raise RiskError(
                "RISK_INVALID_STATE",
                f"risk is {case.status}, cannot dismiss",
            )
        case.status = RiskStatus.DISMISSED
        case.resolution = reason
        case.resolved_at = timezone.now()
        case.version += 1
        case.save(
            update_fields=[
                "status",
                "resolution",
                "resolved_at",
                "version",
                "updated_at",
            ]
        )
        return case

    # ---- 内部 ----

    @staticmethod
    @transaction.atomic
    def _upsert_risk(
        tenant_id: int,
        person_id,
        credential_id: uuid.UUID,
        risk_type: str,
        severity: str,
        due_at: date | None = None,
    ) -> HrQualificationRiskCase | None:
        """去重创建 RiskCase。"""
        HrPerson.objects.select_for_update().get(id=person_id.pk)
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
