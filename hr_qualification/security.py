"""Sensitive-field helpers for HR09 qualification data.

Certificate numbers are never used as display values. The database keeps:
- a one-way SHA-256 match hash for exact-match lookup within an already
  tenant-scoped query;
- a Fernet-encrypted ciphertext for governed recovery/use cases.

A dedicated ``HR_QUALIFICATION_FIELD_KEY`` may be configured. When omitted,
Django ``SECRET_KEY`` is used as key material so fresh installs stay usable;
production deployments should set the dedicated key and keep it in the secret
manager alongside the application secret.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


_PREFIX = b"hr09:v1:"


def _fernet() -> Fernet:
    material = os.getenv("HR_QUALIFICATION_FIELD_KEY") or settings.SECRET_KEY
    raw = str(material).encode("utf-8")
    # Accept a valid Fernet key directly; otherwise derive stable key bytes
    # from secret material without persisting the material itself.
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


def certificate_no_hash(certificate_no: str) -> str:
    value = (certificate_no or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def encrypt_certificate_no(certificate_no: str) -> bytes | None:
    value = (certificate_no or "").strip()
    if not value:
        return None
    return _PREFIX + _fernet().encrypt(value.encode("utf-8"))


def decrypt_certificate_no(ciphertext: bytes | bytearray | memoryview | None) -> str:
    """Decrypt current ciphertext. Legacy plain-byte rows are never returned as plaintext.

    Legacy rows created before this guard intentionally raise ``InvalidToken``;
    they must be re-entered/rotated through a governed remediation instead of
    silently treating unencrypted database bytes as safe ciphertext.
    """
    if not ciphertext:
        return ""
    raw = bytes(ciphertext)
    if not raw.startswith(_PREFIX):
        raise InvalidToken("legacy unencrypted HR09 certificate value")
    return _fernet().decrypt(raw[len(_PREFIX) :]).decode("utf-8")
