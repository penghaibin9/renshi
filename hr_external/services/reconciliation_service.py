"""
hr_external/services/reconciliation_service.py —— 对账（S6/S9，总册 §115/§97/§47）。

- Academic identity drift：HrExternalAcademicIdentity.status 与教务侧不一致 → Risk=ACADEMIC_IDENTITY_DRIFT；
- Access drift：grant 状态与 provisioning request 不一致 / ended engagement 仍有 active access → Risk；
- Legacy projection drift（S9）单独。
- 每项产出 LifecycleEvent（Risk 事件），不直接改 Authority（§46）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hr_external.constants import (
    AccessGrantStatus,
    AcademicIdentityStatus,
    ExternalEngagementStatus,
    RiskSeverity,
    RiskType,
)
from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalAcademicIdentity,
    HrExternalEngagement,
    HrExternalLifecycleEvent,
)


@dataclass
class ReconciliationReport:
    checked: int = 0
    drift: list = field(default_factory=list)

    @property
    def drift_count(self) -> int:
        return len(self.drift)


class ReconciliationService:
    def reconcile_academic_identities(self, *, tenant_id: int) -> ReconciliationReport:
        """检查 ended/suspended 聘期仍有 active academic identity（§97/§138.15 历史保留但未来排课停止）。"""
        report = ReconciliationReport()
        ended_eng_ids = set(
            HrExternalEngagement.objects.filter(
                tenant_id=tenant_id,
                status__in=[
                    ExternalEngagementStatus.ENDED,
                    ExternalEngagementStatus.EXPIRED,
                    ExternalEngagementStatus.ARCHIVED,
                ],
            ).values_list("id", flat=True)
        )
        active_identities = HrExternalAcademicIdentity.objects.filter(
            tenant_id=tenant_id, status=AcademicIdentityStatus.ACTIVE
        ).select_related("engagement_id")
        report.checked = active_identities.count()
        for ident in active_identities:
            if ident.engagement_id_id in ended_eng_ids:
                report.drift.append(
                    {
                        "riskType": RiskType.ACADEMIC_IDENTITY_DRIFT,
                        "severity": RiskSeverity.HIGH,
                        "engagementId": str(ident.engagement_id_id),
                        "note": "academic identity active but engagement ended",
                    }
                )
                self._record_risk(
                    tenant_id=tenant_id,
                    engagement_id=ident.engagement_id_id,
                    risk_type=RiskType.ACADEMIC_IDENTITY_DRIFT,
                    severity=RiskSeverity.HIGH,
                    note="academic identity active but engagement ended",
                )
        return report

    def reconcile_access_grants(self, *, tenant_id: int) -> ReconciliationReport:
        """检查 ended engagement 仍有 active/pending grant（§67/§138.18）。"""
        report = ReconciliationReport()
        ended_eng_ids = set(
            HrExternalEngagement.objects.filter(
                tenant_id=tenant_id,
                status__in=[
                    ExternalEngagementStatus.ENDED,
                    ExternalEngagementStatus.EXPIRED,
                    ExternalEngagementStatus.ARCHIVED,
                ],
            ).values_list("id", flat=True)
        )
        stale_grants = HrExternalAccessGrant.objects.filter(
            tenant_id=tenant_id,
            status__in=[AccessGrantStatus.PENDING, AccessGrantStatus.GRANTED],
        ).select_related("engagement_id")
        report.checked = stale_grants.count()
        for grant in stale_grants:
            if grant.engagement_id_id in ended_eng_ids:
                report.drift.append(
                    {
                        "riskType": RiskType.ACCESS_OUTLIVES_ENGAGEMENT,
                        "severity": RiskSeverity.CRITICAL,
                        "engagementId": str(grant.engagement_id_id),
                        "grantId": str(grant.id),
                        "note": "ended engagement still has active access grant",
                    }
                )
                self._record_risk(
                    tenant_id=tenant_id,
                    engagement_id=grant.engagement_id_id,
                    risk_type=RiskType.ACCESS_OUTLIVES_ENGAGEMENT,
                    severity=RiskSeverity.CRITICAL,
                    note="ended engagement still has active access grant",
                )
        return report

    def _record_risk(
        self, *, tenant_id: int, engagement_id, risk_type: str, severity: str, note: str
    ) -> None:
        HrExternalLifecycleEvent.objects.create(
            tenant_id=tenant_id,
            event_type=f"Risk:{risk_type}",
            event_version=1,
            aggregate_type="ExternalEngagement",
            aggregate_id=engagement_id,
            idempotency_key=f"risk:{risk_type}:{engagement_id}",
            payload_json={"note": note, "riskType": risk_type, "severity": severity},
            status="PUBLISHED",
        )
