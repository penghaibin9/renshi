"""HR09 sensitive certificate-number encryption.

The DB stores a Fernet token, never the certificate number encoded as plain
bytes. Deployments may set HR09_CERTIFICATE_ENCRYPTION_KEY to a stable secret;
otherwise Django SECRET_KEY is used as the key source.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


_TOKEN_PREFIX = b"gAAAA"


def _fernet(tenant_id: int) -> Fernet:
    if not tenant_id:
        raise ValueError("tenant_id is required for HR09 certificate encryption")
    source = getattr(settings, "HR09_CERTIFICATE_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    material = f"{source}:hr09:certificate:{int(tenant_id)}".encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
    return Fernet(key)


def encrypt_certificate_no(tenant_id: int, certificate_no: str | bytes | None) -> bytes | None:
    if certificate_no in (None, "", b""):
        return None
    raw = certificate_no if isinstance(certificate_no, bytes) else str(certificate_no).encode("utf-8")
    if raw.startswith(_TOKEN_PREFIX):
        # Already a Fernet token. Do not double-encrypt on unrelated model saves.
        return raw
    return _fernet(tenant_id).encrypt(raw)


def decrypt_certificate_no(tenant_id: int, token: bytes | memoryview | None) -> str:
    if not token:
        return ""
    raw = bytes(token)
    try:
        return _fernet(tenant_id).decrypt(raw).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("HR09 certificate number ciphertext is invalid for this tenant") from exc


def is_encrypted_certificate_no(value: bytes | memoryview | None) -> bool:
    return bool(value) and bytes(value).startswith(_TOKEN_PREFIX)
