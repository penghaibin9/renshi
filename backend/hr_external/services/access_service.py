"""
hr_external/services/access_service.py —— 外聘访问生命周期（S6，总册 §66-68/§94-99/§104/§105）。

- Activation 后按 category 的 access_policy_code 创建 scoped AccessGrant + ProvisioningRequest（GRANT）；
- expires_at <= engagement.end_at + allowed_grace（§67/§95）；账号寿命不得长期超过 Engagement（§138.18）；
- 一个 Person 多 Engagement → scoped grants 聚合，一个 Engagement 退出不误杀另一个（§98/§99/§138.14）；
- 撤权失败：Engagement=ENDED + Revocation=FAILED_RETRYABLE + Risk=CRITICAL，不反转 Engagement（§105）；
- 外聘默认不授予 HR_EMPLOYEE/FULL_OA/ADMIN（§94）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_external.constants import (
    AccessGrantStatus,
    ExternalEngagementStatus,
    ExternalTaskStatus,
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

MINIMUM_ACCESS_POLICY = {
    "EXTERNAL_PORTAL": {"roleCode": "EXTERNAL_TEACHER_PORTAL", "graceDays": 0},
}
SUPPORTED_ACCESS_POLICY_CODES = {
    "AUTO_MINIMAL",
    "PORTAL_ONLY",
    "PORTAL_ACADEMIC_SCOPED",
    "PORTAL_LIBRARY",
    "PORTAL_ACADEMIC_LIBRARY",
}


class AccessScopeInvalid(Exception):
    code = "EXTERNAL_ACCESS_SCOPE_INVALID"


class GrantAlreadyExists(Exception):
    code = "VERSION_CONFLICT"


class AccessService:
    def __init__(self, iam_provider: Optional[IamProvisioningProvider] = None):
        self.iam = iam_provider or IamProvisioningProvider()

    def policy_for_category(self, category) -> dict:
        """Resolve a bounded least-privilege policy from the category code."""
        if category is None:
            raise AccessScopeInvalid("External category is unavailable inside tenant")
        code = (category.access_policy_code or "AUTO_MINIMAL").strip().upper()
        if code not in SUPPORTED_ACCESS_POLICY_CODES:
            raise AccessScopeInvalid(f"Unknown external access policy code: {code}")
        policy = {system: dict(rule) for system, rule in MINIMUM_ACCESS_POLICY.items()}
        if code in {"PORTAL_LIBRARY", "PORTAL_ACADEMIC_LIBRARY"}:
            policy["LIBRARY"] = {"roleCode": "LIBRARY_EXTERNAL", "graceDays": 7}
        return policy

    @staticmethod
    def _queue_revoke(*, tenant_id: int, engagement, grant):
        base_key = f"revoke:{grant.id}"
        defaults = {
            "engagement_id": engagement,
            "target_system": grant.target_system,
            "operation": ProvisioningOperation.REVOKE,
            "scope_json": {
                "roleCode": grant.role_code,
                "engagementId": str(engagement.id),
            },
            "status": ProvisioningStatus.PENDING,
        }
        request, created = HrExternalProvisioningRequest.objects.get_or_create(
            tenant_id=tenant_id,
            idempotency_key=base_key,
            defaults=defaults,
        )
        if not created and request.status in (
            ProvisioningStatus.FAILED,
            ProvisioningStatus.SKIPPED,
        ):
            request, _ = HrExternalProvisioningRequest.objects.get_or_create(
                tenant_id=tenant_id,
                idempotency_key=f"{base_key}:v{grant.version + 1}",
                defaults=defaults,
            )
        return request

    @transaction.atomic
    def provision_engagement_access(
        self,
        *,
        tenant_id: int,
        engagement: HrExternalEngagement,
    ) -> list[HrExternalAccessGrant]:
        """Activation 后创建 scoped grants + GRANT provisioning requests（§43 step8/§104）。"""
        from hr_external.models import HrExternalCategory

        engagement = (
            HrExternalEngagement.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(engagement, "pk", None))
            .first()
        )
        if engagement is None:
            raise AccessScopeInvalid("Engagement does not belong to tenant")
        if engagement.status not in (
            ExternalEngagementStatus.ACTIVE,
            ExternalEngagementStatus.REVIEW_DUE,
            ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
        ):
            raise AccessScopeInvalid(
                f"Engagement status {engagement.status} is not eligible for access"
            )

        category = HrExternalCategory.objects.filter(
            tenant_id=tenant_id, id=engagement.category_id_id
        ).first()
        policy = self.policy_for_category(category)
        policy_code = (category.access_policy_code or "AUTO_MINIMAL").strip().upper()
        if category.allow_teaching and policy_code in {
            "AUTO_MINIMAL", "PORTAL_ACADEMIC_SCOPED", "PORTAL_ACADEMIC_LIBRARY"
        }:
            from hr_external.models import HrExternalServiceTask

            teaching_refs = list(
                HrExternalServiceTask.objects.filter(
                    tenant_id=tenant_id,
                    engagement_id=engagement,
                    source_domain="ACADEMIC",
                )
                .exclude(status__in=(ExternalTaskStatus.DRAFT, ExternalTaskStatus.CANCELLED))
                .exclude(source_object_id="")
                .order_by("source_object_id")
                .values_list("source_object_id", flat=True)[:500]
            )
            if teaching_refs:
                policy["ACADEMIC"] = {
                    "roleCode": "ACADEMIC_TEACHER",
                    "graceDays": 0,
                    "scope": {"teachingTaskRefs": teaching_refs},
                }

        from hr_external.services.academic_identity_service import AcademicIdentityService

        academic_service = AcademicIdentityService()
        if "ACADEMIC" in policy:
            academic_service.ensure_for_engagement(
                tenant_id=tenant_id, engagement=engagement
            )
        else:
            academic_service.deactivate_for_engagement(
                tenant_id=tenant_id, engagement=engagement
            )

        allowed_pairs = {
            (system, str(rule.get("roleCode", "")))
            for system, rule in policy.items()
        }
        existing_grants = list(
            HrExternalAccessGrant.objects.select_for_update()
            .filter(tenant_id=tenant_id, engagement_id=engagement)
            .exclude(status=AccessGrantStatus.REVOKED)
        )
        obsolete_grants = [
            grant
            for grant in existing_grants
            if (grant.target_system, grant.role_code) not in allowed_pairs
        ]
        for grant in obsolete_grants:
            pending_superseded = []
            for pending in HrExternalProvisioningRequest.objects.filter(
                tenant_id=tenant_id,
                engagement_id=engagement,
                target_system=grant.target_system,
                operation__in=(ProvisioningOperation.GRANT, ProvisioningOperation.UPDATE),
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            ):
                if str((pending.scope_json or {}).get("roleCode", "")) == grant.role_code:
                    pending_superseded.append(pending.id)
            if pending_superseded:
                HrExternalProvisioningRequest.objects.filter(
                    tenant_id=tenant_id, id__in=pending_superseded
                ).update(
                    status=ProvisioningStatus.SKIPPED,
                    error_message="SUPERSEDED_BY_REVOKE",
                    next_attempt_at=None,
                    updated_at=timezone.now(),
                )
            self._queue_revoke(
                tenant_id=tenant_id,
                engagement=engagement,
                grant=grant,
            )
            grant.status = AccessGrantStatus.PENDING
            grant.version += 1
            grant.save(update_fields=["status", "version", "updated_at"])

        grants = []
        end_dt = (
            timezone.make_aware(
                datetime.combine(engagement.end_at, datetime.min.time())
            )
            if engagement.end_at
            else None
        )
        for system, rule in policy.items():
            expires_at = end_dt + timedelta(days=rule.get("graceDays", 0)) if end_dt else None
            role_code = rule.get("roleCode", "")
            desired_scope = {
                "engagementId": str(engagement.id),
                **dict(rule.get("scope") or {}),
            }
            grant = (
                HrExternalAccessGrant.objects.select_for_update()
                .filter(
                    tenant_id=tenant_id,
                    engagement_id=engagement,
                    target_system=system,
                    role_code=role_code,
                )
                .first()
            )
            operation = ProvisioningOperation.GRANT
            force_versioned_grant = False
            if grant is None:
                grant = HrExternalAccessGrant.objects.create(
                    tenant_id=tenant_id,
                    engagement_id=engagement,
                    target_system=system,
                    role_code=role_code,
                    scope_json=desired_scope,
                    granted_at=timezone.now(),
                    expires_at=expires_at,
                    status=AccessGrantStatus.PENDING,
                )
            else:
                open_revokes = HrExternalProvisioningRequest.objects.filter(
                    tenant_id=tenant_id,
                    engagement_id=engagement,
                    target_system=system,
                    operation=ProvisioningOperation.REVOKE,
                    status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
                )
                if open_revokes.exists() or grant.status in (
                    AccessGrantStatus.REVOKED,
                    AccessGrantStatus.REVOKE_FAILED,
                ):
                    open_revokes.update(
                        status=ProvisioningStatus.SKIPPED,
                        error_message="SUPERSEDED_BY_GRANT",
                        next_attempt_at=None,
                        updated_at=timezone.now(),
                    )
                    grant.status = AccessGrantStatus.PENDING
                    grant.revoked_at = None
                    grant.version += 1
                    grant.save(
                        update_fields=["status", "revoked_at", "version", "updated_at"]
                    )
                    force_versioned_grant = True
            if grant.scope_json != desired_scope or grant.expires_at != expires_at:
                grant.scope_json = desired_scope
                grant.expires_at = expires_at
                grant.status = AccessGrantStatus.PENDING
                grant.version += 1
                grant.save(
                    update_fields=[
                        "scope_json", "expires_at", "status", "version", "updated_at"
                    ]
                )
                if not force_versioned_grant:
                    operation = ProvisioningOperation.UPDATE
            request_scope = {
                "roleCode": role_code,
                **desired_scope,
            }
            if operation == ProvisioningOperation.UPDATE:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {"scope": request_scope, "expiresAt": expires_at.isoformat() if expires_at else None},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()[:24]
                idempotency_key = f"update:{grant.id}:{fingerprint}"
            elif force_versioned_grant:
                idempotency_key = f"grant:{grant.id}:v{grant.version}"
            else:
                idempotency_key = f"grant:{engagement.id}:{system}"
            HrExternalProvisioningRequest.objects.get_or_create(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                defaults={
                    "engagement_id": engagement,
                    "target_system": system,
                    "operation": operation,
                    "scope_json": request_scope,
                    "status": ProvisioningStatus.PENDING,
                },
            )
            grants.append(grant)
        return grants

    @transaction.atomic
    def confirm_grant(
        self,
        grant: HrExternalAccessGrant,
        *,
        tenant_id: int,
        external_ref: str = "",
    ):
        """记录 IAM 下发成功回执；由正式调度与对账任务驱动。"""
        grant = (
            HrExternalAccessGrant.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(grant, "pk", None))
            .first()
        )
        if grant is None:
            raise AccessScopeInvalid("Access grant does not belong to tenant")
        grant.status = AccessGrantStatus.GRANTED
        grant.provisioning_ref = external_ref or grant.provisioning_ref
        grant.version += 1
        grant.save(
            update_fields=["status", "provisioning_ref", "version", "updated_at"]
        )
        return grant

    @transaction.atomic
    def revoke_engagement_access(
        self,
        *,
        tenant_id: int,
        engagement: HrExternalEngagement,
    ) -> list[HrExternalAccessGrant]:
        """ExternalEngagementEnding → 逐 grant 发起 REVOKE（§66/§105）。"""
        engagement = (
            HrExternalEngagement.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(engagement, "pk", None))
            .first()
        )
        if engagement is None:
            raise AccessScopeInvalid("Engagement does not belong to tenant")
        from hr_external.services.academic_identity_service import AcademicIdentityService

        AcademicIdentityService().deactivate_for_engagement(
            tenant_id=tenant_id, engagement=engagement
        )
        grants = list(
            HrExternalAccessGrant.objects.select_for_update().filter(
                tenant_id=tenant_id,
                engagement_id=engagement,
                status__in=[
                    AccessGrantStatus.PENDING,
                    AccessGrantStatus.GRANTED,
                    AccessGrantStatus.FAILED_RETRYABLE,
                    AccessGrantStatus.REVOKE_FAILED,
                ],
            )
        )
        for grant in grants:
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=tenant_id,
                engagement_id=engagement,
                target_system=grant.target_system,
                operation__in=(ProvisioningOperation.GRANT, ProvisioningOperation.UPDATE),
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            ).update(
                status=ProvisioningStatus.SKIPPED,
                error_message="SUPERSEDED_BY_REVOKE",
                next_attempt_at=None,
                updated_at=timezone.now(),
            )
            self._queue_revoke(
                tenant_id=tenant_id,
                engagement=engagement,
                grant=grant,
            )
            grant.status = AccessGrantStatus.REVOKE_FAILED if grant.status == AccessGrantStatus.FAILED_RETRYABLE else AccessGrantStatus.PENDING
            grant.version += 1
            grant.save(update_fields=["status", "version", "updated_at"])
        return grants

    @transaction.atomic
    def mark_revoked(
        self, grant: HrExternalAccessGrant, *, tenant_id: int, revoked_at=None
    ):
        grant = (
            HrExternalAccessGrant.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(grant, "pk", None))
            .first()
        )
        if grant is None:
            raise AccessScopeInvalid("Access grant does not belong to tenant")
        grant.status = AccessGrantStatus.REVOKED
        grant.revoked_at = revoked_at or timezone.now()
        grant.version += 1
        grant.save(update_fields=["status", "revoked_at", "version", "updated_at"])
        return grant

    def raise_revocation_risk(self, *, tenant_id: int, engagement_id, note: str):
        """撤权失败 → Risk=CRITICAL（§105）；不反转 Engagement。"""
        from hr_external.models import HrExternalLifecycleEvent

        HrExternalLifecycleEvent.objects.get_or_create(
            tenant_id=tenant_id,
            idempotency_key=f"revokefail:{engagement_id}:{note[:40]}",
            defaults={
                "event_type": "ExternalAccessRevocationFailed",
                "event_version": 1,
                "aggregate_type": "ExternalEngagement",
                "aggregate_id": engagement_id,
                "payload_json": {"note": note, "risk": RiskSeverity.CRITICAL},
                "status": "PUBLISHED",
            },
        )
