"""HR04 candidate identity protection shared by portal and HR services."""

from __future__ import annotations

import hashlib

from cryptography.fernet import InvalidToken
from django.conf import settings

from horilla.security.field_keyring import decrypt_text, encrypt_text, keyed_fingerprint, needs_rewrap

_PREFIX = "hr04:v2"


def normalize_candidate_national_id(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())


def _raw_keyring() -> str:
    return str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()


def _fingerprint_secret() -> str:
    return str(getattr(settings, "FIELD_FINGERPRINT_KEY", "") or "").strip()


def legacy_candidate_id_hash(tenant_id: int, national_id: str) -> str:
    """Exact Round6 compatibility: hash the caller-provided stripped value.

    Round6 did not uppercase/remove punctuation before hashing.  Keeping this
    exact function prevents a key-rotation release from silently losing exact
    matches for historical rows (for example an ID ending in lowercase ``x``).
    """
    value = str(national_id or "").strip()
    if not value:
        return ""
    return hashlib.sha256(f"{int(tenant_id)}:{value}".encode("utf-8")).hexdigest()


def normalized_legacy_candidate_id_hash(tenant_id: int, national_id: str) -> str:
    """Compatibility for Round7 pre-release rows written with normalized legacy hashes."""
    value = normalize_candidate_national_id(national_id)
    if not value:
        return ""
    return hashlib.sha256(f"{int(tenant_id)}:{value}".encode("utf-8")).hexdigest()


def candidate_id_hash(tenant_id: int, national_id: str) -> str:
    value = normalize_candidate_national_id(national_id)
    if not value:
        return ""
    secret = _fingerprint_secret()
    if not secret:
        return legacy_candidate_id_hash(tenant_id, value)
    return keyed_fingerprint(
        secret,
        namespace="hr04.candidate-national-id",
        tenant_id=int(tenant_id),
        normalized_value=value,
    )


def candidate_id_hash_candidates(tenant_id: int, national_id: str) -> tuple[str, ...]:
    current = candidate_id_hash(tenant_id, national_id)
    legacy_raw = legacy_candidate_id_hash(tenant_id, national_id)
    legacy_normalized = normalized_legacy_candidate_id_hash(tenant_id, national_id)
    return tuple(
        dict.fromkeys(
            value for value in (current, legacy_raw, legacy_normalized) if value
        )
    )


def encrypt_candidate_national_id(national_id: str) -> str:
    value = normalize_candidate_national_id(national_id)
    raw_keys = _raw_keyring()
    if not value or not raw_keys:
        return ""
    return encrypt_text(raw_keys, value, prefix=_PREFIX)


def decrypt_candidate_national_id(ciphertext: str) -> str:
    value = str(ciphertext or "")
    if not value:
        return ""
    if not value.startswith(f"{_PREFIX}:"):
        raise InvalidToken("HR04 legacy candidate row has no governed ciphertext")
    return decrypt_text(_raw_keyring(), value, prefix=_PREFIX)


def needs_candidate_rewrap(ciphertext: str) -> bool:
    raw_keys = _raw_keyring()
    if not raw_keys or not ciphertext:
        return False
    return needs_rewrap(str(ciphertext), raw_keys, prefix=_PREFIX)
