"""
hr_qualification/services/credential_service.py —— PersonCredential CRUD + 状态流转。

总册 §107：
- submit-verification → 变更状态为 UNDER_VERIFICATION
- verify → 创建 Verification 记录，更新 current_verification_status
- renew → 新建 PersonCredential（不覆盖原记录）→ 创建 Renewal 链
- suspend/revoke → 状态变更为 SUSPENDED/REVOKED + StatusEvent 记录

安全/一致性：
- 所有 Authority 写入口必须显式 tenant_id；只知道 credential UUID 不能跨校写；
- 所有 select_for_update 都在 transaction.atomic 内；
- 公共 verify() 只允许“人工原件核验”直接产生 VERIFIED，且必须有 verified_by；
- 官方库/第三方/迁移/导入等 VERIFIED 必须后续由受信 Provider Adapter 专用入口写入，
  禁止客户端只提交 provider 字符串就把证书激活；
- PROVIDER_UNAVAILABLE / MISMATCH 等永远不能把 credential 变 ACTIVE。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from hr_qualification.constants import (
    CredentialStatus,
    RenewalType,
    VerificationResult,
    VerificationType,
)
from hr_qualification.models import (
    HrCredentialRenewal,
    HrCredentialStatusEvent,
    HrCredentialVerification,
    HrPersonCredential,
)


class CredentialError(Exception):
    """证书操作异常。"""

    def __init__(self, message: str, code: str = "CREDENTIAL_OPERATION_ERROR"):
        self.code = code
        super().__init__(message)


_TERMINAL_OR_REPLACED = {
    CredentialStatus.REVOKED,
    CredentialStatus.INVALID,
    CredentialStatus.SUPERSEDED,
    CredentialStatus.ARCHIVED,
}


class CredentialService:
    """人员证书权威操作服务。"""

    @staticmethod
    def _lock_credential(*, tenant_id: int, credential_id: uuid.UUID) -> HrPersonCredential:
        if not tenant_id:
            raise CredentialError("tenant_id is required", "TENANT_CONTEXT_REQUIRED")
        try:
            return HrPersonCredential.objects.select_for_update().get(
                id=credential_id,
                tenant_id=tenant_id,
            )
        except ObjectDoesNotExist as exc:
            # 不区分“别的 tenant 存在该 UUID”和“完全不存在”，避免 IDOR 枚举。
            raise CredentialError(
                "Credential not found inside tenant.",
                "CREDENTIAL_NOT_FOUND",
            ) from exc

    @staticmethod
    def _assert_public_verified_allowed(
        *,
        verification_type: str,
        result: VerificationResult,
        verified_by: int | None,
        provider: str,
    ) -> None:
        if result != VerificationResult.VERIFIED:
            return

        normalized_type = str(verification_type)
        provider_key = (provider or "").strip().lower()
        if any(token in provider_key for token in ("mock", "fake", "stub", "test")):
            raise CredentialError(
                "Mock/test verification provider cannot produce VERIFIED authority facts.",
                "VERIFICATION_PROVIDER_NOT_TRUSTED",
            )

        if normalized_type != VerificationType.MANUAL_ORIGINAL_REVIEW:
            raise CredentialError(
                "VERIFIED from non-manual channels requires a trusted Provider Adapter; "
                "the public credential service cannot self-attest provider trust.",
                "VERIFICATION_TRUSTED_PROVIDER_REQUIRED",
            )
        if verified_by is None:
            raise CredentialError(
                "Manual original review requires an authenticated verifier.",
                "VERIFICATION_ACTOR_REQUIRED",
            )

    @staticmethod
    @transaction.atomic
    def submit_for_verification(
        tenant_id: int,
        credential_id: uuid.UUID,
        actor_id: int | None = None,
    ) -> HrPersonCredential:
        credential = CredentialService._lock_credential(
            tenant_id=tenant_id,
            credential_id=credential_id,
        )
        _assert_can_transition(credential, CredentialStatus.UNDER_VERIFICATION)

        old_status = credential.status
        credential.status = CredentialStatus.UNDER_VERIFICATION
        credential.version += 1
        credential.save(update_fields=["status", "version", "updated_at"])

        HrCredentialStatusEvent.objects.create(
            credential_id=credential,
            from_status=old_status,
            to_status=CredentialStatus.UNDER_VERIFICATION,
            reason="Submitted for verification",
            actor_id=actor_id,
        )
        return credential

    @staticmethod
    @transaction.atomic
    def verify(
        tenant_id: int,
        credential_id: uuid.UUID,
        verification_type: str,
        result: VerificationResult,
        verified_by: int | None = None,
        provider: str = "",
        provider_reference: str = "",
        notes: str = "",
    ) -> HrCredentialVerification:
        credential = CredentialService._lock_credential(
            tenant_id=tenant_id,
            credential_id=credential_id,
        )
        if credential.status in _TERMINAL_OR_REPLACED:
            raise CredentialError(
                f"Credential in {credential.status} status cannot be verified.",
                "CREDENTIAL_STATUS_BLOCKED",
            )

        try:
            normalized_result = (
                result
                if isinstance(result, VerificationResult)
                else VerificationResult(result)
            )
        except ValueError as exc:
            raise CredentialError(
                f"Unsupported verification result: {result}",
                "VERIFICATION_RESULT_INVALID",
            ) from exc

        CredentialService._assert_public_verified_allowed(
            verification_type=verification_type,
            result=normalized_result,
            verified_by=verified_by,
            provider=provider,
        )

        now = datetime.now(timezone.utc)
        verification = HrCredentialVerification.objects.create(
            credential_id=credential,
            verification_type=verification_type,
            provider=provider,
            provider_reference=provider_reference,
            result=normalized_result.value,
            verified_by=verified_by,
            verified_at=now,
            notes=notes,
        )

        # 核验结果是审计快照；失败/不可用也要记录，但不能变 ACTIVE。
        credential.current_verification_status = normalized_result.value
        credential.last_verified_at = now
        update_fields = [
            "current_verification_status",
            "last_verified_at",
            "version",
            "updated_at",
        ]

        if normalized_result == VerificationResult.VERIFIED:
            if credential.status in (
                CredentialStatus.DRAFT,
                CredentialStatus.SUBMITTED,
                CredentialStatus.UNDER_VERIFICATION,
            ):
                old_status = credential.status
                credential.status = CredentialStatus.ACTIVE
                update_fields.append("status")
                HrCredentialStatusEvent.objects.create(
                    credential_id=credential,
                    from_status=old_status,
                    to_status=CredentialStatus.ACTIVE,
                    reason=f"Verified ({verification_type})",
                    actor_id=verified_by,
                )

        credential.version += 1
        credential.save(update_fields=list(dict.fromkeys(update_fields)))
        return verification

    @staticmethod
    @transaction.atomic
    def renew(
        tenant_id: int,
        credential_id: uuid.UUID,
        new_credential_data: dict,
        renewal_type: str = RenewalType.SAME_LEVEL,
        reason: str = "",
    ) -> tuple[HrPersonCredential, HrCredentialRenewal]:
        """续证：新建证书（不覆盖 valid_to），建立 original → new 代际链。"""
        original = CredentialService._lock_credential(
            tenant_id=tenant_id,
            credential_id=credential_id,
        )
        if original.status in _TERMINAL_OR_REPLACED:
            raise CredentialError(
                f"Credential in {original.status} status cannot be renewed.",
                "CREDENTIAL_STATUS_BLOCKED",
            )

        old_status = original.status
        original.status = CredentialStatus.SUPERSEDED
        original.version += 1
        original.save(update_fields=["status", "version", "updated_at"])

        HrCredentialStatusEvent.objects.create(
            credential_id=original,
            from_status=old_status,
            to_status=CredentialStatus.SUPERSEDED,
            reason=f"Superseded by renewal ({renewal_type})",
        )

        # 明确继承 Authority identity/tenant；new_credential_data 不能覆盖这些边界字段。
        forbidden = {
            "tenant_id",
            "person_id",
            "person_id_id",
            "staff_master_id",
            "staff_master_id_id",
            "external_engagement_id",
            "catalog_item_id",
            "catalog_item_id_id",
            "status",
            "version",
        }
        attempted = forbidden.intersection(new_credential_data)
        if attempted:
            raise CredentialError(
                f"Renewal payload cannot override authority identity fields: {sorted(attempted)}",
                "CREDENTIAL_RENEWAL_IDENTITY_OVERRIDE",
            )

        base_data = {
            "tenant_id": original.tenant_id,
            "person_id": original.person_id,
            "staff_master_id": original.staff_master_id,
            "external_engagement_id": original.external_engagement_id,
            "catalog_item_id": original.catalog_item_id,
            "credential_name_snapshot": original.credential_name_snapshot,
            "level_code": original.level_code,
            "issuer_name": original.issuer_name,
            "status": CredentialStatus.DRAFT,
            "source": original.source,
            "self_reported": original.self_reported,
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
    @transaction.atomic
    def suspend(
        tenant_id: int,
        credential_id: uuid.UUID,
        actor_id: int | None = None,
        reason: str = "",
    ) -> HrPersonCredential:
        return _change_status_locked(
            tenant_id=tenant_id,
            credential_id=credential_id,
            target_status=CredentialStatus.SUSPENDED,
            actor_id=actor_id,
            reason=reason,
        )

    @staticmethod
    @transaction.atomic
    def revoke(
        tenant_id: int,
        credential_id: uuid.UUID,
        actor_id: int | None = None,
        reason: str = "",
    ) -> HrPersonCredential:
        return _change_status_locked(
            tenant_id=tenant_id,
            credential_id=credential_id,
            target_status=CredentialStatus.REVOKED,
            actor_id=actor_id,
            reason=reason,
        )


def _assert_can_transition(credential: HrPersonCredential, target: str) -> None:
    """正式 ACTIVE 后不可走通用编辑/重新提交；需走专用服务。"""
    if credential.status in (
        CredentialStatus.ACTIVE,
        CredentialStatus.EXPIRED,
        CredentialStatus.SUSPENDED,
        CredentialStatus.REVOKED,
        CredentialStatus.INVALID,
        CredentialStatus.SUPERSEDED,
        CredentialStatus.ARCHIVED,
    ):
        raise CredentialError(
            f"Cannot directly edit credential in {credential.status} status. "
            f"Use dedicated service (renew/suspend/revoke).",
            "CREDENTIAL_STATUS_BLOCKED",
        )


def _change_status_locked(
    *,
    tenant_id: int,
    credential_id: uuid.UUID,
    target_status: str,
    actor_id: int | None = None,
    reason: str = "",
) -> HrPersonCredential:
    credential = CredentialService._lock_credential(
        tenant_id=tenant_id,
        credential_id=credential_id,
    )
    if credential.status in (CredentialStatus.SUPERSEDED, CredentialStatus.ARCHIVED):
        raise CredentialError(
            f"Credential in {credential.status} status cannot transition to {target_status}.",
            "CREDENTIAL_STATUS_BLOCKED",
        )
    if credential.status == target_status:
        return credential

    old_status = credential.status
    credential.status = target_status
    credential.version += 1
    credential.save(update_fields=["status", "version", "updated_at"])

    HrCredentialStatusEvent.objects.create(
        credential_id=credential,
        from_status=old_status,
        to_status=target_status,
        reason=reason,
        actor_id=actor_id,
    )
    return credential
