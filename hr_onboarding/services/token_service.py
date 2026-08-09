"""
hr_onboarding/services/token_service.py

Portal token 安全（总册 §9.7 REWRITE）：
- 明文只在签发时返回一次；数据库只存 SHA-256 hash；
- 不入日志、不入 URL analytics、不入数据库明文；
- expiry/purpose/revoke/last_used/attempt 限流；
- 公共 onboarding URL 不可枚举（00 §134）。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from hr_onboarding.api.exceptions import PortalTokenExpiredError, PortalTokenRevokedError
from hr_onboarding.constants import PortalTokenPurpose, PortalTokenStatus
from hr_onboarding.models import HrPrehirePortalAccess

MAX_FAILED_ATTEMPTS = 5
DEFAULT_TTL_DAYS = 30


def generate_token() -> str:
    """生成不可枚举的明文 token（32 字节 URL-safe）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hash 存储。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_portal_access(
    *,
    tenant_id: int,
    case,
    purpose: str = PortalTokenPurpose.PREHIRE_ACCESS,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> tuple[HrPrehirePortalAccess, str]:
    """
    签发 Portal 访问。返回 (portal, plaintext_token)。
    明文 token 只在本函数返回值中出现一次；调用方负责不落日志。
    """
    plaintext = generate_token()
    HrPrehirePortalAccess.objects.filter(tenant_id=tenant_id, case=case).delete()
    portal = HrPrehirePortalAccess.objects.create(
        tenant_id=tenant_id,
        case=case,
        token_hash=hash_token(plaintext),
        purpose=purpose,
        expires_at=timezone.now() + timedelta(days=ttl_days),
        status=PortalTokenStatus.ACTIVE,
    )
    return portal, plaintext


def resolve_portal_access(*, tenant_id: Optional[int], token: str) -> HrPrehirePortalAccess:
    """
    按明文 token 解析 portal（hash 查找）。
    - tenant_id 为 None：公开 Portal 入口，仅凭全局唯一 token_hash 解析（00 §134 以 token 为授权，裸 tenant id 不是授权）；
    - tenant_id 给定：管理端/内部校验时附加 tenant 过滤（fail-closed）。
    - 过期 → PortalTokenExpiredError；revoked/used → PortalTokenRevokedError；
    - 超过失败次数 → 锁定（revoke）。
    """
    token_hash = hash_token(token)
    qs = HrPrehirePortalAccess.objects.filter(token_hash=token_hash)
    if tenant_id is not None:
        qs = qs.filter(tenant_id=tenant_id)
    portal = qs.select_related("case").first()
    if portal is None:
        return None  # 统一走 404 语义，不泄露存在性

    now = timezone.now()
    if portal.expires_at and portal.expires_at <= now:
        portal.status = PortalTokenStatus.EXPIRED
        portal.save(update_fields=["status"])
        raise PortalTokenExpiredError()
    if portal.status in (PortalTokenStatus.REVOKED, PortalTokenStatus.EXPIRED):
        raise PortalTokenRevokedError()
    if portal.failed_attempts >= MAX_FAILED_ATTEMPTS:
        portal.status = PortalTokenStatus.REVOKED
        portal.save(update_fields=["status"])
        raise PortalTokenRevokedError("token locked after too many failed attempts")

    portal.last_used_at = now
    portal.save(update_fields=["last_used_at"])
    return portal


def mark_token_failed(portal: HrPrehirePortalAccess) -> None:
    portal.failed_attempts += 1
    portal.save(update_fields=["failed_attempts"])


def revoke_portal_access(portal: HrPrehirePortalAccess) -> None:
    from hr_onboarding.constants import PortalTokenStatus

    portal.status = PortalTokenStatus.REVOKED
    portal.revoked_at = timezone.now()
    portal.save(update_fields=["status", "revoked_at"])
