"""Reliable HR08-to-academic identity lifecycle."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_external.constants import AcademicIdentityStatus, ProvisioningStatus
from hr_external.integrations.academic import AcademicProvider
from hr_external.integrations.base import ProviderStatus
from hr_external.models import (
    HrExternalAcademicIdentity,
    HrExternalAcademicProvisioningRequest,
    HrExternalEngagement,
)


class AcademicIdentityScopeInvalid(Exception):
    code = "EXTERNAL_ACADEMIC_IDENTITY_SCOPE_INVALID"


class AcademicIdentityService:
    MAX_ATTEMPTS = 5
    CLAIM_LEASE = timedelta(minutes=5)

    def __init__(self, provider=None):
        self.provider = provider or AcademicProvider()

    @transaction.atomic
    def ensure_for_engagement(self, *, tenant_id: int, engagement):
        engagement = (
            HrExternalEngagement.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(engagement, "pk", None))
            .first()
        )
        if engagement is None:
            raise AcademicIdentityScopeInvalid("Engagement does not belong to tenant")
        identity, created = HrExternalAcademicIdentity.objects.select_for_update().get_or_create(
            tenant_id=tenant_id,
            engagement_id=engagement,
            defaults={
                "external_teacher_no": (
                    f"EXT{tenant_id}-{str(engagement.id).replace('-', '')[:16]}"
                )[:32],
                "valid_from": engagement.start_at,
                "valid_to": engagement.end_at,
                "status": AcademicIdentityStatus.PENDING,
            },
        )
        desired_changed = (
            identity.valid_from != engagement.start_at
            or identity.valid_to != engagement.end_at
        )
        if desired_changed:
            identity.valid_from = engagement.start_at
            identity.valid_to = engagement.end_at
            identity.status = AcademicIdentityStatus.PENDING
            identity.version += 1
            identity.save(
                update_fields=["valid_from", "valid_to", "status", "version", "updated_at"]
            )
        open_deactivations = identity.provisioning_requests.filter(
            operation=HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE,
            status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
        )
        reactivating = open_deactivations.exists() or identity.status in (
            AcademicIdentityStatus.REVOKED,
            AcademicIdentityStatus.EXPIRED,
        )
        if reactivating:
            open_deactivations.update(
                status=ProvisioningStatus.SKIPPED,
                error_message="SUPERSEDED_BY_ACTIVATE",
                next_attempt_at=None,
                updated_at=timezone.now(),
            )
            identity.status = AcademicIdentityStatus.PENDING
            identity.version += 1
            identity.save(update_fields=["status", "version", "updated_at"])
        if created:
            key = f"academic-activate:{identity.id}"
        elif desired_changed or reactivating:
            key = f"academic-activate:{identity.id}:v{identity.version}"
        else:
            key = f"academic-activate:{identity.id}"
        HrExternalAcademicProvisioningRequest.objects.get_or_create(
            tenant_id=tenant_id,
            idempotency_key=key,
            defaults={
                "academic_identity_id": identity,
                "operation": HrExternalAcademicProvisioningRequest.Operation.ACTIVATE,
                "status": ProvisioningStatus.PENDING,
            },
        )
        return identity

    @transaction.atomic
    def deactivate_for_engagement(self, *, tenant_id: int, engagement):
        identity = (
            HrExternalAcademicIdentity.objects.select_for_update()
            .filter(tenant_id=tenant_id, engagement_id=getattr(engagement, "pk", engagement))
            .first()
        )
        if identity is None:
            return None
        if (
            identity.status == AcademicIdentityStatus.REVOKED
            and not identity.provisioning_requests.filter(
                operation=HrExternalAcademicProvisioningRequest.Operation.ACTIVATE,
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            ).exists()
        ):
            return identity
        identity.provisioning_requests.filter(
            operation=HrExternalAcademicProvisioningRequest.Operation.ACTIVATE,
            status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
        ).update(
            status=ProvisioningStatus.SKIPPED,
            error_message="SUPERSEDED_BY_DEACTIVATE",
            next_attempt_at=None,
            updated_at=timezone.now(),
        )
        base_key = f"academic-deactivate:{identity.id}"
        request, created = HrExternalAcademicProvisioningRequest.objects.get_or_create(
            tenant_id=tenant_id,
            idempotency_key=base_key,
            defaults={
                "academic_identity_id": identity,
                "operation": HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE,
                "status": ProvisioningStatus.PENDING,
            },
        )
        if not created and request.status in (ProvisioningStatus.FAILED, ProvisioningStatus.SKIPPED):
            HrExternalAcademicProvisioningRequest.objects.get_or_create(
                tenant_id=tenant_id,
                idempotency_key=f"{base_key}:v{identity.version + 1}",
                defaults={
                    "academic_identity_id": identity,
                    "operation": HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE,
                    "status": ProvisioningStatus.PENDING,
                },
            )
        identity.drift_note = "DEACTIVATION_PENDING"
        identity.version += 1
        identity.save(update_fields=["drift_note", "version", "updated_at"])
        return identity

    def dispatch_batch(self, *, tenant_id: int, limit: int = 200) -> dict:
        now = timezone.now()
        ids = list(
            HrExternalAcademicProvisioningRequest.objects.filter(
                tenant_id=tenant_id,
                status__in=(ProvisioningStatus.PENDING, ProvisioningStatus.FAILED_RETRYABLE),
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("created_at", "id")
            .values_list("id", flat=True)[:limit]
        )
        summary = {
            "selected": len(ids),
            "succeeded": 0,
            "retrying": 0,
            "failed": 0,
            "skipped": 0,
        }
        for request_id in ids:
            summary[self.dispatch_one(tenant_id=tenant_id, request_id=request_id)] += 1
        return summary

    def dispatch_one(self, *, tenant_id: int, request_id) -> str:
        request = self._claim_request(tenant_id=tenant_id, request_id=request_id)
        if request is None:
            return "skipped"
        identity = request.academic_identity_id
        try:
            if request.operation == HrExternalAcademicProvisioningRequest.Operation.ACTIVATE:
                result = self.provider.activate_teacher_identity(
                    tenant_id=tenant_id,
                    external_teacher_no=identity.external_teacher_no,
                    academic_teacher_id=identity.academic_teacher_id,
                    valid_from=identity.valid_from.isoformat(),
                    valid_to=identity.valid_to.isoformat() if identity.valid_to else None,
                    idempotency_key=request.idempotency_key,
                )
            elif request.operation == HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE:
                result = self.provider.deactivate_teacher_identity(
                    tenant_id=tenant_id,
                    academic_teacher_id=identity.academic_teacher_id,
                    external_teacher_no=identity.external_teacher_no,
                    idempotency_key=request.idempotency_key,
                )
            else:
                return self._record_failure(
                    request, identity, "ACADEMIC_OPERATION_UNSUPPORTED", False
                )
        except Exception:
            outcome = self._record_failure(
                request, identity, "ACADEMIC_PROVIDER_EXCEPTION", True
            )
            self._raise_terminal_deactivation_risk(
                request=request,
                identity=identity,
                outcome=outcome,
                note="ACADEMIC_IDENTITY:PROVIDER_EXCEPTION",
            )
            return outcome
        if result.status == ProviderStatus.OK:
            receipt = dict(result.data or {})
            if not receipt.get("receiptId"):
                outcome = self._record_failure(
                    request, identity, "PROVIDER_RECEIPT_INVALID", False
                )
                self._raise_terminal_deactivation_risk(
                    request=request,
                    identity=identity,
                    outcome=outcome,
                    note="ACADEMIC_IDENTITY:PROVIDER_RECEIPT_INVALID",
                )
                return outcome
            if (
                request.operation == HrExternalAcademicProvisioningRequest.Operation.ACTIVATE
                and not (receipt.get("academicTeacherId") or identity.academic_teacher_id)
            ):
                return self._record_failure(
                    request, identity, "ACADEMIC_TEACHER_ID_MISSING", False
                )
            return self._record_success(request, identity, receipt)
        outcome = self._record_failure(
            request,
            identity,
            result.error_code or "ACADEMIC_PROVIDER_FAILED",
            result.status == ProviderStatus.UNAVAILABLE,
        )
        self._raise_terminal_deactivation_risk(
            request=request,
            identity=identity,
            outcome=outcome,
            note=f"ACADEMIC_IDENTITY:{result.error_code or 'PROVIDER_FAILED'}",
        )
        return outcome

    @transaction.atomic
    def _claim_request(self, *, tenant_id: int, request_id):
        """Lease one due row so concurrent schedulers cannot double-dispatch it."""
        now = timezone.now()
        request = (
            HrExternalAcademicProvisioningRequest.objects.select_for_update()
            .select_related("academic_identity_id")
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
    def _raise_terminal_deactivation_risk(
        *, request, identity, outcome: str, note: str
    ) -> None:
        if (
            outcome != "failed"
            or request.operation
            != HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE
        ):
            return
        from hr_external.services.access_service import AccessService

        AccessService().raise_revocation_risk(
            tenant_id=request.tenant_id,
            engagement_id=identity.engagement_id_id,
            note=note,
        )

    @transaction.atomic
    def _record_success(self, request, identity, receipt: dict) -> str:
        request = HrExternalAcademicProvisioningRequest.objects.select_for_update().get(
            tenant_id=request.tenant_id, id=request.id
        )
        if request.status == ProvisioningStatus.SUCCESS:
            return "skipped"
        if request.status not in (
            ProvisioningStatus.PENDING,
            ProvisioningStatus.FAILED_RETRYABLE,
        ):
            return "skipped"
        identity = HrExternalAcademicIdentity.objects.select_for_update().get(
            tenant_id=request.tenant_id, id=identity.id
        )
        request.status = ProvisioningStatus.SUCCESS
        request.external_ref = str(receipt.get("receiptId", ""))[:128]
        request.provider_receipt_json = receipt
        request.error_message = ""
        request.next_attempt_at = None
        request.version += 1
        request.save(update_fields=[
            "status", "external_ref", "provider_receipt_json", "error_message",
            "next_attempt_at", "version", "updated_at",
        ])
        if request.operation == HrExternalAcademicProvisioningRequest.Operation.ACTIVATE:
            identity.academic_teacher_id = str(
                receipt.get("academicTeacherId") or identity.academic_teacher_id
            )[:64]
            identity.status = AcademicIdentityStatus.ACTIVE
        else:
            identity.status = AcademicIdentityStatus.REVOKED
        identity.last_sync_at = timezone.now()
        identity.drift_note = ""
        identity.version += 1
        identity.save(update_fields=[
            "academic_teacher_id", "status", "last_sync_at", "drift_note",
            "version", "updated_at",
        ])
        return "succeeded"

    @transaction.atomic
    def _record_failure(self, request, identity, code: str, retryable: bool) -> str:
        request = HrExternalAcademicProvisioningRequest.objects.select_for_update().get(
            tenant_id=request.tenant_id, id=request.id
        )
        if request.status == ProvisioningStatus.SUCCESS:
            return "skipped"
        if request.status not in (
            ProvisioningStatus.PENDING,
            ProvisioningStatus.FAILED_RETRYABLE,
        ):
            return "skipped"
        request.retry_count += 1
        retryable = retryable and request.retry_count < self.MAX_ATTEMPTS
        request.status = (
            ProvisioningStatus.FAILED_RETRYABLE if retryable else ProvisioningStatus.FAILED
        )
        request.error_message = str(code)[:512]
        request.next_attempt_at = (
            timezone.now() + timedelta(minutes=min(2 ** request.retry_count, 60))
            if retryable
            else None
        )
        request.version += 1
        request.save(update_fields=[
            "retry_count", "status", "error_message", "next_attempt_at",
            "version", "updated_at",
        ])
        identity = HrExternalAcademicIdentity.objects.select_for_update().get(
            tenant_id=request.tenant_id, id=identity.id
        )
        identity.drift_note = str(code)[:512]
        identity.version += 1
        identity.save(update_fields=["drift_note", "version", "updated_at"])
        return "retrying" if retryable else "failed"
