"""
hr_external/services/access_service.py —— 外聘访问生命周期（S6，总册 §66-68/§94-99/§104/§105）。

- Activation 后按 category 的 access_policy_code 创建 scoped AccessGrant + ProvisioningRequest（GRANT）；
- expires_at <= engagement.end_at + allowed_grace（§67/§95）；账号寿命不得长期超过 Engagement（§138.18）；
- 一个 Person 多 Engagement → scoped grants 聚合，一个 Engagement 退出不误杀另一个（§98/§99/§138.14）；
- 撤权失败：Engagement=ENDED + Revocation=FAILED_RETRYABLE + Risk=CRITICAL，不反转 Engagement（§105）；
- 外聘默认不授予 HR_EMPLOYEE/FULL_OA/ADMIN（§94）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_external.constants import (
    AccessGrantStatus,
    ProvisioningOperation,
    ProvisioningStatus,
    RiskSeverity,
)
from hr_external.integrations.iam import IamProvisioningProvider
from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalEngagement,
    HrExternalProvisioningRequest,
)

DEFAULT_ACCESS_POLICY = {
    "EXTERNAL_PORTAL": {"roleCode": "EXTERNAL_TEACHER_PORTAL", "graceDays": 0},
    "ACADEMIC": {"roleCode": "ACADEMIC_TEACHER", "graceDays": 0},
    "LIBRARY": {"roleCode": "LIBRARY_EXTERNAL", "graceDays": 7},
}


class AccessScopeInvalid(Exception):
    code = "EXTERNAL_ACCESS_SCOPE_INVALID"


class GrantAlreadyExists(Exception):
    code = "VERSION_CONFLICT"


class AccessService:
    def __init__(self, iam_provider: Optional[IamProvisioningProvider] = None):
        self.iam = iam_provider or IamProvisioningProvider()

    def policy_for_category(self, category) -> dict:
        """按 category.access_policy_code 返回目标系统×角色×grace 的默认策略。
        # [总控占位] 访问策略模型未建（S6 后接 policy 字典），先用内置默认集。"""
        code = (category.access_policy_code or "").strip()
        if not code:
            return dict(DEFAULT_ACCESS_POLICY)
        return dict(DEFAULT_ACCESS_POLICY)  # 占位：后续按 policy 配置解析

    @transaction.atomic
    def provision_engagement_access(
        self,
        *,
        tenant_id: int,
        engagement: HrExternalEngagement,
    ) -> list[HrExternalAccessGrant]:
        """Activation 后创建 scoped grants + GRANT provisioning requests（§43 step8/§104）。"""
        from hr_external.models import HrExternalCategory

        category = HrExternalCategory.objects.filter(
            tenant_id=tenant_id, id=engagement.category_id_id
        ).first()
        policy = self.policy_for_category(category)

        grants = []
        end_dt = datetime.combine(engagement.end_at, datetime.min.time()) if engagement.end_at else None
        for system, rule in policy.items():
            expires_at = end_dt + timedelta(days=rule.get("graceDays", 0)) if end_dt else None
            grant = HrExternalAccessGrant.objects.create(
                tenant_id=tenant_id,
                engagement_id=engagement,
                target_system=system,
                role_code=rule.get("roleCode", ""),
                scope_json={"engagementId": str(engagement.id)},
                granted_at=timezone.now(),
                expires_at=expires_at,
                status=AccessGrantStatus.PENDING,
            )
            HrExternalProvisioningRequest.objects.create(
                tenant_id=tenant_id,
                engagement_id=engagement,
                target_system=system,
                operation=ProvisioningOperation.GRANT,
                scope_json={"roleCode": rule.get("roleCode", ""), "engagementId": str(engagement.id)},
                idempotency_key=f"grant:{engagement.id}:{system}",
                status=ProvisioningStatus.PENDING,
            )
            grants.append(grant)
        return grants

    def confirm_grant(self, grant: HrExternalAccessGrant, *, external_ref: str = ""):
        """IAM 下发成功回执（Provider 占位下由 scheduler/reconciliation 驱动）。"""
        grant.status = AccessGrantStatus.GRANTED
        grant.provisioning_ref = external_ref or grant.provisioning_ref
        grant.save(update_fields=["status", "provisioning_ref", "updated_at"])

    @transaction.atomic
    def revoke_engagement_access(
        self,
        *,
        tenant_id: int,
        engagement: HrExternalEngagement,
    ) -> list[HrExternalAccessGrant]:
        """ExternalEngagementEnding → 逐 grant 发起 REVOKE（§66/§105）。"""
        grants = list(
            HrExternalAccessGrant.objects.filter(
                tenant_id=tenant_id,
                engagement_id=engagement,
                status__in=[AccessGrantStatus.PENDING, AccessGrantStatus.GRANTED, AccessGrantStatus.FAILED_RETRYABLE],
            )
        )
        for grant in grants:
            HrExternalProvisioningRequest.objects.create(
                tenant_id=tenant_id,
                engagement_id=engagement,
                target_system=grant.target_system,
                operation=ProvisioningOperation.REVOKE,
                scope_json={"roleCode": grant.role_code, "engagementId": str(engagement.id)},
                idempotency_key=f"revoke:{grant.id}",
                status=ProvisioningStatus.PENDING,
            )
            grant.status = AccessGrantStatus.REVOKE_FAILED if grant.status == AccessGrantStatus.FAILED_RETRYABLE else AccessGrantStatus.PENDING
            grant.save(update_fields=["status", "updated_at"])
        return grants

    def mark_revoked(self, grant: HrExternalAccessGrant, *, revoked_at=None):
        grant.status = AccessGrantStatus.REVOKED
        grant.revoked_at = revoked_at or timezone.now()
        grant.save(update_fields=["status", "revoked_at", "updated_at"])

    def raise_revocation_risk(self, *, tenant_id: int, engagement_id, note: str):
        """撤权失败 → Risk=CRITICAL（§105）；不反转 Engagement。"""
        from hr_external.models import HrExternalLifecycleEvent

        HrExternalLifecycleEvent.objects.create(
            tenant_id=tenant_id,
            event_type="ExternalAccessRevocationFailed",
            event_version=1,
            aggregate_type="ExternalEngagement",
            aggregate_id=engagement_id,
            idempotency_key=f"revokefail:{engagement_id}:{note[:40]}",
            payload_json={"note": note, "risk": RiskSeverity.CRITICAL},
            status="PUBLISHED",
        )
