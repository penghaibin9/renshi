"""
hr_onboarding/services/security.py

HR05 敏感值加密（总册 §27 / §40 / 00 §37）：
- bank_json 等 HIGH_SENSITIVE 数据 Fernet 加密存储；
- 密钥派生与 hr_staff.services.crypto 一致（基于 settings.SECRET_KEY），保证全系统可互通；
- 明文不落库、不入日志；解密仅授权路径调用。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_ENCRYPTED_MARKER = "__hr05_enc__"

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet, InvalidToken

        secret = getattr(settings, "SECRET_KEY", "")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_sensitive_value(value: dict) -> dict:
    """把 dict 加密为 {marker: ciphertext}（Fernet）。空 dict 原样返回。"""
    if not value:
        return {}
    try:
        ciphertext = _get_fernet().encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")).decode("ascii")
    except Exception:
        logger.exception("sensitive encrypt failed")
        return {}
    return {_ENCRYPTED_MARKER: ciphertext}


def decrypt_sensitive_value(stored: dict) -> dict:
    """解密 {marker: ciphertext} → dict；失败/非加密返回空 dict（不泄漏）。"""
    if not stored or not isinstance(stored, dict):
        return {}
    ciphertext = stored.get(_ENCRYPTED_MARKER)
    if not ciphertext:
        return stored  # 非加密内容原样返回（兼容旧数据/非敏感字段）
    try:
        from cryptography.fernet import InvalidToken

        plain = _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        return json.loads(plain)
    except InvalidToken:
        logger.error("sensitive decrypt failed (InvalidToken)")
        return {}
    except Exception:
        logger.exception("sensitive decrypt failed")
        return {}
