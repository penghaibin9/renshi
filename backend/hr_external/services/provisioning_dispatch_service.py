"""Durable HR08 IAM outbox dispatcher with idempotent retries."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_external.constants import (
    AccessGrantStatus,
    ProvisioningOperation,
    ProvisioningStatus,
)
from hr_external.integrations.base import ProviderStatus
from hr_external.integrations.iam import IamProvisioningProvider
from hr_external.models import HrExternalAccessGrant, HrExternalProvisioningRequest


class ProvisioningDispatchService:
    MAX_ATTEMPTS = 5
    CLAIM_LEASE = timedelta(minutes=5)

    def __init__(self, iam_provider=None):
        self.iam = iam_provider or IamProvisioningProvider()

    def dispatch_batch(self, *, tenant_id: int, limit: int = 200) -> dict:
        now = timezone.now()
        request_ids = list(
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=tenant_id,
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:limit]
        )
        summary = {
            "selected": len(request_ids),
            "succeeded": 0,
            "retrying": 0,
            "failed": 0,
            "skipped": 0,
        }
        for request_id in request_ids:
            outcome = self.dispatch_one(tenant_id=tenant_id, request_id=request_id)
            summary[outcome] += 1
        return summary

    def dispatch_one(self, *, tenant_id: int, request_id) -> str:
        request = self._claim_request(tenant_id=tenant_id, request_id=request_id)
        if request is None:
            return "skipped"
        grant = (
            HrExternalAccessGrant.objects.filter(
                tenant_id=tenant_id,
                engagement_id=request.engagement_id,
                target_system=request.target_system,
                role_code=str(request.scope_json.get("roleCode", "")),
            )
            .order_by("id")
            .first()
        )
        if grant is None:
            outcome = self._record_failure(
                request, None, "ACCESS_GRANT_NOT_FOUND", retryable=False
            )
            self._raise_terminal_revoke_risk(
                request=request,
                outcome=outcome,
                note=f"{request.target_system}:ACCESS_GRANT_NOT_FOUND",
            )
            return outcome

        kwargs = {
            "tenant_id": tenant_id,
            "target_system": grant.target_system,
            "role_code": grant.role_code,
            "scope_json": dict(grant.scope_json or {}),
            "idempotency_key": request.idempotency_key,
        }
        try:
            if request.operation in (ProvisioningOperation.GRANT, ProvisioningOperation.UPDATE):
                result = self.iam.provision_grant(
                    **kwargs,
                    expires_at=grant.expires_at.isoformat() if grant.expires_at else None,
                )
            elif request.operation == ProvisioningOperation.REVOKE:
                result = self.iam.revoke_grant(**kwargs)
            else:
                outcome = self._record_failure(
                    request, grant, "PROVISIONING_OPERATION_UNSUPPORTED", retryable=False
                )
                self._raise_terminal_revoke_risk(
                    request=request,
                    outcome=outcome,
                    note=f"{request.target_system}:PROVISIONING_OPERATION_UNSUPPORTED",
                )
                return outcome
        except Exception:
            outcome = self._record_failure(
                request, grant, "PROVIDER_EXCEPTION", retryable=True
            )
            self._raise_terminal_revoke_risk(
                request=request,
                outcome=outcome,
                note=f"{request.target_system}:PROVIDER_EXCEPTION",
            )
            return outcome

        if result.status == ProviderStatus.OK:
            receipt = dict(result.data or {})
            if not receipt.get("receiptId"):
                outcome = self._record_failure(
                    request, grant, "PROVIDER_RECEIPT_INVALID", retryable=False
                )
                self._raise_terminal_revoke_risk(
                    request=request,
                    outcome=outcome,
                    note=f"{request.target_system}:PROVIDER_RECEIPT_INVALID",
                )
                return outcome
            return self._record_success(request, grant, receipt)
        retryable = result.status == ProviderStatus.UNAVAILABLE
        outcome = self._record_failure(
            request,
            grant,
            result.error_code or "PROVIDER_FAILED",
            retryable=retryable,
        )
        self._raise_terminal_revoke_risk(
            request=request,
            outcome=outcome,
            note=f"{request.target_system}:{result.error_code or 'PROVIDER_FAILED'}",
        )
        return outcome

    @transaction.atomic
    def _claim_request(self, *, tenant_id: int, request_id):
        """Lease one due row so concurrent schedulers cannot double-dispatch it."""
        now = timezone.now()
        request = (
            HrExternalProvisioningRequest.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                id=request_id,
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .first()
        )
        if request is None:
            return None
        request.next_attempt_at = now + self.CLAIM_LEASE
        request.save(update_fields=["next_attempt_at", "updated_at"])
        return request

    @staticmethod
    def _raise_terminal_revoke_risk(*, request, outcome: str, note: str) -> None:
        if outcome != "failed" or request.operation != ProvisioningOperation.REVOKE:
            return
        from hr_external.services.access_service import AccessService

        AccessService().raise_revocation_risk(
            tenant_id=request.tenant_id,
            engagement_id=request.engagement_id_id,
            note=note,
        )

    @transaction.atomic
    def _record_success(self, request, grant, receipt: dict) -> str:
        locked = HrExternalProvisioningRequest.objects.select_for_update().get(
            id=request.id, tenant_id=request.tenant_id
        )
        if locked.status == ProvisioningStatus.SUCCESS:
            return "skipped"
        if locked.status not in (
            ProvisioningStatus.PENDING,
            ProvisioningStatus.FAILED_RETRYABLE,
        ):
            return "skipped"
        locked.status = ProvisioningStatus.SUCCESS
        locked.external_ref = str(receipt.get("receiptId", ""))[:128]
        locked.provider_receipt_json = receipt
        locked.error_message = ""
        locked.next_attempt_at = None
        locked.version += 1
        locked.save(update_fields=[
            "status", "external_ref", "provider_receipt_json", "error_message",
            "next_attempt_at", "version", "updated_at",
        ])
        grant = HrExternalAccessGrant.objects.select_for_update().get(
            id=grant.id, tenant_id=request.tenant_id
        )
        if request.operation in (ProvisioningOperation.GRANT, ProvisioningOperation.UPDATE):
            grant.status = AccessGrantStatus.GRANTED
            grant.provisioning_ref = locked.external_ref
            fields = ["status", "provisioning_ref", "version", "updated_at"]
        else:
            grant.status = AccessGrantStatus.REVOKED
            grant.revoked_at = timezone.now()
            fields = ["status", "revoked_at", "version", "updated_at"]
        grant.version += 1
        grant.save(update_fields=fields)
        return "succeeded"

    @transaction.atomic
    def _record_failure(self, request, grant, code: str, *, retryable: bool) -> str:
        locked = HrExternalProvisioningRequest.objects.select_for_update().get(
            id=request.id, tenant_id=request.tenant_id
        )
        if locked.status == ProvisioningStatus.SUCCESS:
            return "skipped"
        if locked.status not in (
            ProvisioningStatus.PENDING,
            ProvisioningStatus.FAILED_RETRYABLE,
        ):
            return "skipped"
        locked.retry_count += 1
        retryable = retryable and locked.retry_count < self.MAX_ATTEMPTS
        locked.status = (
            ProvisioningStatus.FAILED_RETRYABLE if retryable else ProvisioningStatus.FAILED
        )
        locked.error_message = str(code or "PROVIDER_FAILED")[:512]
        locked.next_attempt_at = (
            timezone.now() + timedelta(minutes=min(2 ** locked.retry_count, 60))
            if retryable
            else None
        )
        locked.version += 1
        locked.save(update_fields=[
            "retry_count", "status", "error_message", "next_attempt_at", "version", "updated_at",
        ])
        if grant is not None:
            grant = HrExternalAccessGrant.objects.select_for_update().get(
                id=grant.id, tenant_id=request.tenant_id
            )
            grant.status = (
                AccessGrantStatus.REVOKE_FAILED
                if request.operation == ProvisioningOperation.REVOKE
                else AccessGrantStatus.FAILED_RETRYABLE
            )
            grant.version += 1
            grant.save(update_fields=["status", "version", "updated_at"])
        return "retrying" if retryable else "failed"
