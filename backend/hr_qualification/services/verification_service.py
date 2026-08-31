"""
hr_qualification/services/verification_service.py —— 核验编排。

总册 §24-25：
- 多种核验类型（MANUAL_ORIGINAL_REVIEW / OFFICIAL_DATABASE / THIRD_PARTY / ISSUER / IMPORT / MIGRATION）
- 每次核验都是追加记录，不覆盖历史
- 核验本身也可过期（verification_valid_until）
- 无真实核验渠道时 → MANUAL_ORIGINAL_REVIEW
- 禁止 mock provider 标记 VERIFIED
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hr_qualification.models import HrCredentialVerification, HrPersonCredential


class VerificationService:
    """证书核验编排服务。"""

    @staticmethod
    def get_latest(credential_id: uuid.UUID) -> HrCredentialVerification | None:
        return (
            HrCredentialVerification.objects
            .filter(credential_id=credential_id)
            .order_by("-verified_at", "-created_at")
            .first()
        )

    @staticmethod
    def get_history(credential_id: uuid.UUID) -> list[HrCredentialVerification]:
        return list(
            HrCredentialVerification.objects
            .filter(credential_id=credential_id)
            .order_by("-verified_at", "-created_at")
        )

    @staticmethod
    def is_verification_stale(
        verification: HrCredentialVerification,
    ) -> bool:
        """检查核验是否过期（如第三方核验要求周期复核）。"""
        if verification.verification_valid_until is None:
            return False
        return verification.verification_valid_until < datetime.now(timezone.utc)

    @staticmethod
    def needs_reverification(
        credential: HrPersonCredential,
        max_age_days: int = 365,
    ) -> bool:
        """判断是否需要重新核验。"""
        if credential.last_verified_at is None:
            return True
        age = datetime.now(timezone.utc) - credential.last_verified_at
        return age.days > max_age_days
