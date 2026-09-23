"""Sensitive certificate helpers for HR09.

Round7 moves certificate encryption onto the shared rotation-capable
``FIELD_ENCRYPTION_KEYS`` keyring and exact-match hashes onto the independent
``FIELD_FINGERPRINT_KEY`` HMAC.  Round6 v1 ciphertext/hash remain readable for
migration and dual-match lookups.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from horilla.security.field_keyring import decrypt_text, encrypt_text, keyed_fingerprint, needs_rewrap

_V1_PREFIX = b"hr09:v1:"
_V2_PREFIX = "hr09:v2"


def _raw_keyring() -> str:
    return str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()


def _fingerprint_secret() -> str:
    return str(getattr(settings, "FIELD_FINGERPRINT_KEY", "") or "").strip()


def _legacy_fernet() -> Fernet:
    material = os.getenv("HR_QUALIFICATION_FIELD_KEY") or settings.SECRET_KEY
    raw = str(material).encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) == 32:
            return Fernet(raw)
    except Exception:
        pass
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(b"renshi:hr09:certificate:v1:" + raw).digest()
    )
    return Fernet(derived)


def legacy_certificate_no_hash(certificate_no: str) -> str:
    value = (certificate_no or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def certificate_no_hash(certificate_no: str, *, tenant_id: int | None = None) -> str:
    value = (certificate_no or "").strip()
    if not value:
        return ""
    secret = _fingerprint_secret()
    if not secret:
        return legacy_certificate_no_hash(value)
    if not tenant_id:
        raise ValueError("tenant_id is required for production certificate fingerprints")
    return keyed_fingerprint(
        secret,
        namespace="hr09.certificate",
        tenant_id=int(tenant_id),
        normalized_value=value,
    )


def certificate_no_hash_candidates(tenant_id: int, certificate_no: str) -> tuple[str, ...]:
    current = certificate_no_hash(certificate_no, tenant_id=int(tenant_id))
    legacy = legacy_certificate_no_hash(certificate_no)
    return tuple(dict.fromkeys(value for value in (current, legacy) if value))


def encrypt_certificate_no(certificate_no: str) -> bytes | None:
    value = (certificate_no or "").strip()
    if not value:
        return None
    raw_keys = _raw_keyring()
    if raw_keys:
        return encrypt_text(raw_keys, value, prefix=_V2_PREFIX).encode("ascii")
    # Local/test compatibility only. Production requires FIELD_ENCRYPTION_KEYS.
    return _V1_PREFIX + _legacy_fernet().encrypt(value.encode("utf-8"))


def decrypt_certificate_no(ciphertext: bytes | bytearray | memoryview | None) -> str:
    if not ciphertext:
        return ""
    raw = bytes(ciphertext)
    if raw.startswith(f"{_V2_PREFIX}:".encode("ascii")):
        return decrypt_text(_raw_keyring(), raw.decode("ascii"), prefix=_V2_PREFIX)
    if not raw.startswith(_V1_PREFIX):
        raise InvalidToken("legacy unencrypted HR09 certificate value")
    return _legacy_fernet().decrypt(raw[len(_V1_PREFIX) :]).decode("utf-8")


def needs_certificate_rewrap(ciphertext: bytes | bytearray | memoryview | None) -> bool:
    raw_keys = _raw_keyring()
    if not raw_keys or not ciphertext:
        return False
    raw = bytes(ciphertext)
    if not raw.startswith(f"{_V2_PREFIX}:".encode("ascii")):
        return True
    return needs_rewrap(raw.decode("ascii"), raw_keys, prefix=_V2_PREFIX)
