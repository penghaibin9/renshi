"""hr_qualification/services/credential_service.py —— PersonCredential CRUD + 状态流转。

总册 §107：
- submit-verification → 变更状态为 UNDER_VERIFICATION
- verify → 创建 Verification 记录，更新 current_verification_status
- renew → 新建 PersonCredential（不覆盖原记录）→ 创建 Renewal 链
- suspend/revoke → 状态变更为 SUSPENDED/REVOKED + StatusEvent 记录

所有 select_for_update 都必须位于 transaction.atomic 内，保证 MySQL 真实行锁语义。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from hr_qualification.constants import CredentialStatus, RenewalType, VerificationResult
from hr_qualification.models import (
    HrCredentialRenewal,
    HrCredentialStatusEvent,
    HrCredentialVerification,
    HrPersonCredential,
)


class CredentialError(Exception):
    """证书操作异常。"""


class CredentialService:
    """人员证书权威操作服务。"""

    @staticmethod
    def submit_for_verification(
        credential_id: uuid.UUID,
        actor_id: int | None = None,
    ) -> HrPersonCredential:
        with transaction.atomic():
            try:
                credential = HrPersonCredential.objects.select_for_update().get(id=credential_id)
            except ObjectDoesNotExist:
                raise CredentialError(f"Credential {credential_id} not found.")

            _assert_can_transition(credential, CredentialStatus.UNDER_VERIFICATION)
            old_status = credential.status
            credential.status = CredentialStatus.UNDER_VERIFICATION
            credential.version += 1
            credential.save()

            HrCredentialStatusEvent.objects.create(
                credential_id=credential,
                from_status=old_status,
                to_status=CredentialStatus.UNDER_VERIFICATION,
                reason="Submitted for verification",
                actor_id=actor_id,
            )
            return credential

    @staticmethod
    def verify(
        credential_id: uuid.UUID,
        verification_type: str,
        result: VerificationResult,
        verified_by: int | None = None,
        provider: str = "",
        provider_reference: str = "",
        notes: str = "",
    ) -> HrCredentialVerification:
        with transaction.atomic():
            try:
                credential = HrPersonCredential.objects.select_for_update().get(id=credential_id)
            except ObjectDoesNotExist:
                raise CredentialError(f"Credential {credential_id} not found.")

            now = datetime.now(timezone.utc)
            verification = HrCredentialVerification.objects.create(
                credential_id=credential,
                verification_type=verification_type,
                provider=provider,
                provider_reference=provider_reference,
                result=result.value,
                verified_by=verified_by,
                verified_at=now,
                notes=notes,
            )

            credential.current_verification_status = result.value
            credential.last_verified_at = now
            if result == VerificationResult.VERIFIED and credential.status in (
                CredentialStatus.DRAFT,
                CredentialStatus.UNDER_VERIFICATION,
            ):
                old_status = credential.status
                credential.status = CredentialStatus.ACTIVE
                HrCredentialStatusEvent.objects.create(
                    credential_id=credential,
                    from_status=old_status,
                    to_status=CredentialStatus.ACTIVE,
                    reason=f"Verified ({verification_type})",
                    actor_id=verified_by,
                )

            credential.version += 1
            credential.save()
            return verification

    @staticmethod
    def renew(
        credential_id: uuid.UUID,
        new_credential_data: dict,
        renewal_type: str = RenewalType.SAME_LEVEL,
        reason: str = "",
    ) -> tuple[HrPersonCredential, HrCredentialRenewal]:
        """续证：新建证书（不覆盖原记录），建立代际链。"""
        with transaction.atomic():
            try:
                original = HrPersonCredential.objects.select_for_update().get(id=credential_id)
            except ObjectDoesNotExist:
                raise CredentialError(f"Credential {credential_id} not found.")

            old_status = original.status
            original.status = CredentialStatus.SUPERSEDED
            original.version += 1
            original.save()

            HrCredentialStatusEvent.objects.create(
                credential_id=original,
                from_status=old_status,
                to_status=CredentialStatus.SUPERSEDED,
                reason=f"Superseded by renewal ({renewal_type})",
            )

            base_data = {
                "tenant_id": original.tenant_id,
                "person_id": original.person_id,
                "staff_master_id": original.staff_master_id,
                "catalog_item_id": original.catalog_item_id,
                "credential_name_snapshot": original.credential_name_snapshot,
                "level_code": original.level_code,
                "issuer_name": original.issuer_name,
                "status": CredentialStatus.DRAFT,
                "source": original.source,
            }
            base_data.update(new_credential_data)
            new_credential = HrPersonCredential.objects.create(**base_data)

            renewal = HrCredentialRenewal.objects.create(
                original_credential_id=original,
                new_credential_id=new_credential,
                renewal_type=renewal_type,
                reason=reason,
            )
            return new_credential, renewal

    @staticmethod
    def suspend(
        credential_id: uuid.UUID,
        actor_id: int | None = None,
        reason: str = "",
    ) -> HrPersonCredential:
        return _change_status(credential_id, CredentialStatus.SUSPENDED, actor_id, reason)

    @staticmethod
    def revoke(
        credential_id: uuid.UUID,
        actor_id: int | None = None,
        reason: str = "",
    ) -> HrPersonCredential:
        return _change_status(credential_id, CredentialStatus.REVOKED, actor_id, reason)


def _assert_can_transition(credential: HrPersonCredential, target: str) -> None:
    if credential.status in (
        CredentialStatus.ACTIVE,
        CredentialStatus.EXPIRED,
        CredentialStatus.SUSPENDED,
        CredentialStatus.REVOKED,
        CredentialStatus.SUPERSEDED,
    ):
        raise CredentialError(
            f"Cannot directly edit credential in {credential.status} status. "
            f"Use dedicated service (renew/suspend/revoke)."
        )


def _change_status(
    credential_id: uuid.UUID,
    target_status: str,
    actor_id: int | None = None,
    reason: str = "",
) -> HrPersonCredential:
    with transaction.atomic():
        try:
            credential = HrPersonCredential.objects.select_for_update().get(id=credential_id)
        except ObjectDoesNotExist:
            raise CredentialError(f"Credential {credential_id} not found.")

        old_status = credential.status
        credential.status = target_status
        credential.version += 1
        credential.save()
        HrCredentialStatusEvent.objects.create(
            credential_id=credential,
            from_status=old_status,
            to_status=target_status,
            reason=reason,
            actor_id=actor_id,
        )
        return credential
