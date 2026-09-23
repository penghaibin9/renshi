"""Versioned field-encryption and keyed-fingerprint helpers.

Production encryption uses ``FIELD_ENCRYPTION_KEYS`` in this form::

    primary:<fernet-key>,previous:<fernet-key>

The first key is the write key.  All listed keys remain readable, which lets an
operator rotate keys without making existing ciphertext unreadable.  Domain
services own their legacy decryptors; this module never silently derives a
production field key from Django ``SECRET_KEY``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class FieldKeyringError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedKeyring:
    keys: tuple[tuple[str, Fernet], ...]

    @property
    def current_id(self) -> str:
        return self.keys[0][0]

    def by_id(self, key_id: str) -> Fernet:
        for candidate_id, fernet in self.keys:
            if candidate_id == key_id:
                return fernet
        raise InvalidToken(f"unknown field encryption key id: {key_id}")


def parse_fernet_keyring(raw: str) -> ParsedKeyring:
    entries: list[tuple[str, Fernet]] = []
    seen: set[str] = set()
    for item in filter(None, (part.strip() for part in str(raw or "").split(","))):
        key_id, separator, key_material = item.partition(":")
        if not separator or not _KEY_ID_RE.fullmatch(key_id):
            raise FieldKeyringError("FIELD_ENCRYPTION_KEYS entries must use key-id:fernet-key")
        if key_id in seen:
            raise FieldKeyringError(f"duplicate field encryption key id: {key_id}")
        try:
            fernet = Fernet(key_material.encode("ascii"))
        except Exception as exc:  # noqa: BLE001 - normalize key parsing failure
            raise FieldKeyringError(f"invalid Fernet key for {key_id}") from exc
        seen.add(key_id)
        entries.append((key_id, fernet))
    if not entries:
        raise FieldKeyringError("FIELD_ENCRYPTION_KEYS is empty")
    return ParsedKeyring(tuple(entries))


def encrypt_text(raw_keys: str, plaintext: str, *, prefix: str) -> str:
    ring = parse_fernet_keyring(raw_keys)
    key_id, fernet = ring.keys[0]
    token = fernet.encrypt(str(plaintext).encode("utf-8")).decode("ascii")
    return f"{prefix}:{key_id}:{token}"


def decrypt_text(raw_keys: str, ciphertext: str, *, prefix: str) -> str:
    marker = f"{prefix}:"
    value = str(ciphertext or "")
    if not value.startswith(marker):
        raise InvalidToken("ciphertext does not use the requested field-keyring envelope")
    remainder = value[len(marker) :]
    key_id, separator, token = remainder.partition(":")
    if not separator or not key_id or not token:
        raise InvalidToken("malformed field-keyring envelope")
    ring = parse_fernet_keyring(raw_keys)
    return ring.by_id(key_id).decrypt(token.encode("ascii")).decode("utf-8")


def current_key_id(raw_keys: str) -> str:
    return parse_fernet_keyring(raw_keys).current_id


def needs_rewrap(ciphertext: str, raw_keys: str, *, prefix: str) -> bool:
    value = str(ciphertext or "")
    marker = f"{prefix}:"
    if not value.startswith(marker):
        return True
    key_id = value[len(marker) :].split(":", 1)[0]
    return key_id != current_key_id(raw_keys)


def keyed_fingerprint(
    secret: str,
    *,
    namespace: str,
    tenant_id: int,
    normalized_value: str,
) -> str:
    """Return a non-reversible, tenant-scoped HMAC fingerprint."""

    material = str(secret or "").encode("utf-8")
    if len(material) < 32:
        raise FieldKeyringError("FIELD_FINGERPRINT_KEY must contain at least 32 bytes")
    value = str(normalized_value or "")
    payload = f"{namespace}:{int(tenant_id)}:{value}".encode("utf-8")
    return hmac.new(material, payload, hashlib.sha256).hexdigest()


def legacy_sha256_fingerprint(*, tenant_id: int, normalized_value: str) -> str:
    """Legacy tenant-scoped SHA-256 used only for transition lookups."""

    value = str(normalized_value or "")
    if not value:
        return ""
    return hashlib.sha256(f"{int(tenant_id)}:{value}".encode("utf-8")).hexdigest()


def first_successful_decrypt(
    ciphertext: bytes,
    fernets: Iterable[Fernet],
) -> bytes:
    last_error: Exception | None = None
    for fernet in fernets:
        try:
            return fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            last_error = exc
    raise InvalidToken("legacy ciphertext could not be decrypted") from last_error
