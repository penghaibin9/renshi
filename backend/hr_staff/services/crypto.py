"""
hr_staff/services/crypto.py —— 身份证明文加密与指纹（HIGH_SENSITIVE）。

设计（总册 §8.3 / §49.6）：
- 使用 cryptography.Fernet，密钥派生自 settings.SECRET_KEY（V1；后续可切换 KMS）。
- 模块导入不触发 cryptography（懒加载），保证轻量 CI/迁移环境可用。
- fingerprint = sha256("tenant:{tenant_id}:{normalized}")，tenant-aware，用于同租户去重。
- 禁止在日志/审计中打印明文。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet, InvalidToken

        secret = getattr(settings, "SECRET_KEY", "")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        _fernet = Fernet(key)
    return _fernet


def normalize_document_number(value: str) -> str:
    """证件号规范化：去空白与常见连字符，统一大写（同租户去重用）。"""
    if not value:
        return ""
    return "".join(ch for ch in str(value).strip().upper() if ch.isalnum())


def encrypt_document_number(tenant_id: int, value: str) -> str:
    """加密证件号；不验证格式，调用方负责。返回密文。"""
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_document_number(ciphertext: str) -> str:
    """解密证件号；失败返回空字符串（不抛给调用方泄漏细节）。"""
    if not ciphertext:
        return ""
    try:
        from cryptography.fernet import InvalidToken

        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("identity document decryption failed (InvalidToken)")
        return ""
    except Exception:  # pragma: no cover - 兜底不泄漏
        logger.error("identity document decryption failed")
        return ""


def document_fingerprint(tenant_id: int, normalized: str) -> str:
    """tenant-aware fingerprint（去重键）。空值返回空串。"""
    if not normalized:
        return ""
    return hashlib.sha256(f"tenant:{tenant_id}:{normalized}".encode("utf-8")).hexdigest()


def mask_document_number(value: str) -> str:
    """默认 API 展示：前 6 + **** + 后 4（长度不足全掩码）。"""
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}****{value[-4:]}"
