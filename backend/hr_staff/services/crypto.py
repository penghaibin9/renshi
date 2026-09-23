"""HR03 high-sensitive identity encryption and exact-match fingerprints.

Round7 production posture:
- writes use the first key in ``FIELD_ENCRYPTION_KEYS`` and carry its key id;
- reads keep compatibility with Round6 ciphertext derived from ``SECRET_KEY``;
- searchable document fingerprints use HMAC-SHA256 with the independent
  ``FIELD_FINGERPRINT_KEY`` rather than a brute-forceable plain SHA-256;
- legacy fingerprints remain queryable until ``rotate_hr_field_security`` has
  rewrapped the database.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from horilla.security.field_keyring import decrypt_text, encrypt_text, keyed_fingerprint, needs_rewrap

logger = logging.getLogger(__name__)

_PREFIX = "hr03:v2"


def _legacy_fernet() -> Fernet:
    secret = str(getattr(settings, "SECRET_KEY", ""))
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _raw_keyring() -> str:
    return str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()


def _fingerprint_secret() -> str:
    return str(getattr(settings, "FIELD_FINGERPRINT_KEY", "") or "").strip()


def normalize_document_number(value: str) -> str:
    if not value:
        return ""
    return "".join(ch for ch in str(value).strip().upper() if ch.isalnum())


def encrypt_document_number(tenant_id: int, value: str) -> str:
    if not value:
        return ""
    raw_keys = _raw_keyring()
    if raw_keys:
        return encrypt_text(raw_keys, str(value), prefix=_PREFIX)
    # Local/test compatibility only. Production requires FIELD_ENCRYPTION_KEYS.
    return _legacy_fernet().encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_document_number(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    value = str(ciphertext)
    try:
        if value.startswith(f"{_PREFIX}:"):
            return decrypt_text(_raw_keyring(), value, prefix=_PREFIX)
        return _legacy_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("identity document decryption failed (InvalidToken)")
        return ""
    except Exception:  # pragma: no cover - never expose secret details
        logger.error("identity document decryption failed")
        return ""


def needs_document_rewrap(ciphertext: str) -> bool:
    raw_keys = _raw_keyring()
    if not raw_keys or not ciphertext:
        return False
    return needs_rewrap(str(ciphertext), raw_keys, prefix=_PREFIX)


def legacy_document_fingerprint(tenant_id: int, normalized: str) -> str:
    if not normalized:
        return ""
    return hashlib.sha256(
        f"tenant:{int(tenant_id)}:{normalized}".encode("utf-8")
    ).hexdigest()


def document_fingerprint(tenant_id: int, normalized: str) -> str:
    if not normalized:
        return ""
    secret = _fingerprint_secret()
    if not secret:
        # Local/test compatibility only. Production requires FIELD_FINGERPRINT_KEY.
        return legacy_document_fingerprint(tenant_id, normalized)
    return keyed_fingerprint(
        secret,
        namespace="hr03.document",
        tenant_id=int(tenant_id),
        normalized_value=normalized,
    )


def document_fingerprint_candidates(tenant_id: int, normalized: str) -> tuple[str, ...]:
    current = document_fingerprint(tenant_id, normalized)
    legacy = legacy_document_fingerprint(tenant_id, normalized)
    return tuple(dict.fromkeys(value for value in (current, legacy) if value))


def mask_document_number(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}****{value[-4:]}"
