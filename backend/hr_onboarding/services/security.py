"""HR05 high-sensitive staging encryption.

Round7 writes use the independent ``FIELD_ENCRYPTION_KEYS`` keyring.  Round6
ciphertext derived from Django ``SECRET_KEY`` remains readable only as a legacy
transition path so production can rewrap it before go-live.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from horilla.security.field_keyring import decrypt_text, encrypt_text, needs_rewrap

logger = logging.getLogger(__name__)

_ENCRYPTED_MARKER = "__hr05_enc__"
_PREFIX = "hr05:v2"


def _raw_keyring() -> str:
    return str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()


def _legacy_fernet() -> Fernet:
    secret = str(getattr(settings, "SECRET_KEY", ""))
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_sensitive_value(value: dict) -> dict:
    if not value:
        return {}
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        raw_keys = _raw_keyring()
        if raw_keys:
            ciphertext = encrypt_text(raw_keys, payload, prefix=_PREFIX)
        else:
            # Local/test compatibility only. Production requires the keyring.
            ciphertext = _legacy_fernet().encrypt(payload.encode("utf-8")).decode("ascii")
    except Exception:
        # Encryption failure must abort the caller before any profile save.
        # Returning an empty dict here would silently erase bank/high-sensitive
        # staging data while making the request look successful.
        logger.exception("sensitive encrypt failed")
        raise
    return {_ENCRYPTED_MARKER: ciphertext}


def decrypt_sensitive_value(stored: dict) -> dict:
    if not stored or not isinstance(stored, dict):
        return {}
    ciphertext = stored.get(_ENCRYPTED_MARKER)
    if not ciphertext:
        return stored  # legacy non-sensitive JSON remains readable
    try:
        value = str(ciphertext)
        if value.startswith(f"{_PREFIX}:"):
            plain = decrypt_text(_raw_keyring(), value, prefix=_PREFIX)
        else:
            plain = _legacy_fernet().decrypt(value.encode("ascii")).decode("utf-8")
        decoded = json.loads(plain)
        return decoded if isinstance(decoded, dict) else {}
    except InvalidToken:
        logger.error("sensitive decrypt failed (InvalidToken)")
        return {}
    except Exception:
        logger.exception("sensitive decrypt failed")
        return {}


def needs_sensitive_rewrap(stored: dict) -> bool:
    raw_keys = _raw_keyring()
    if not raw_keys or not isinstance(stored, dict):
        return False
    ciphertext = stored.get(_ENCRYPTED_MARKER)
    if not ciphertext:
        return bool(stored)
    return needs_rewrap(str(ciphertext), raw_keys, prefix=_PREFIX)
