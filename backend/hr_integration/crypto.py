from __future__ import annotations

import json
from django.conf import settings
from horilla.security.field_keyring import decrypt_text, encrypt_text

_PREFIX = "hrint:v1"


class IntegrationSecretError(ValueError):
    pass


def encrypt_secret_payload(payload: dict) -> str:
    if not payload:
        return ""
    raw_keys = str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()
    if not raw_keys:
        raise IntegrationSecretError("FIELD_ENCRYPTION_KEYS 未配置，禁止保存接口密钥")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encrypt_text(raw_keys, raw, prefix=_PREFIX)


def decrypt_secret_payload(ciphertext: str) -> dict:
    if not ciphertext:
        return {}
    raw_keys = str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()
    if not raw_keys:
        raise IntegrationSecretError("FIELD_ENCRYPTION_KEYS 未配置，无法读取接口密钥")
    try:
        value = json.loads(decrypt_text(raw_keys, ciphertext, prefix=_PREFIX))
    except Exception as exc:
        raise IntegrationSecretError("接口密钥解密失败") from exc
    if not isinstance(value, dict):
        raise IntegrationSecretError("接口密钥格式错误")
    return value
