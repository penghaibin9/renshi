"""Authenticated encryption for database fields that contain credentials."""

from __future__ import annotations

import base64
import hashlib
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


ENCRYPTED_PREFIX = "renshi:enc:v1:"
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class FieldEncryptionError(ImproperlyConfigured):
    """Raised when encrypted credential data cannot be safely interpreted."""


def _derive_development_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(
        b"renshi:database-field-encryption:development:v1:" + secret_key.encode()
    ).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=16)
def _keyring(raw_configuration: str, secret_key: str):
    entries = []
    seen = set()
    raw_configuration = str(raw_configuration or "").strip()
    if not raw_configuration:
        if not secret_key:
            raise FieldEncryptionError("No database field encryption key is configured.")
        return (("development", Fernet(_derive_development_key(secret_key))),)

    for raw_entry in raw_configuration.split(","):
        key_id, separator, key_material = raw_entry.strip().partition(":")
        if not separator or not _KEY_ID_PATTERN.fullmatch(key_id):
            raise FieldEncryptionError(
                "FIELD_ENCRYPTION_KEYS entries must use key-id:fernet-key."
            )
        if key_id in seen:
            raise FieldEncryptionError(
                f"FIELD_ENCRYPTION_KEYS contains duplicate key id {key_id!r}."
            )
        try:
            cipher = Fernet(key_material.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise FieldEncryptionError(
                f"FIELD_ENCRYPTION_KEYS key {key_id!r} is not a valid Fernet key."
            ) from exc
        seen.add(key_id)
        entries.append((key_id, cipher))
    return tuple(entries)


def configured_keyring():
    return _keyring(
        str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or ""),
        str(getattr(settings, "SECRET_KEY", "") or ""),
    )


def is_encrypted_value(value) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_value(value) -> str:
    if value is None or value == "":
        return value
    text = str(value)
    if is_encrypted_value(text):
        # Accept only a ciphertext that can actually be authenticated.
        decrypt_value(text)
        return text
    key_id, cipher = configured_keyring()[0]
    token = cipher.encrypt(text.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_PREFIX}{key_id}:{token}"


def decrypt_value(value) -> str:
    if value is None or value == "":
        return value
    text = str(value)
    if not is_encrypted_value(text):
        # Compatibility for rows written before the encryption migration. Data
        # migrations re-save these values through EncryptedTextField.
        return text
    remainder = text[len(ENCRYPTED_PREFIX) :]
    key_id, separator, token = remainder.partition(":")
    if not separator or not token:
        raise FieldEncryptionError("Encrypted database credential has an invalid envelope.")
    ciphers = dict(configured_keyring())
    cipher = ciphers.get(key_id)
    if cipher is None:
        raise FieldEncryptionError(
            f"Encrypted database credential requires unavailable key {key_id!r}."
        )
    try:
        return cipher.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise FieldEncryptionError(
            "Encrypted database credential failed integrity verification."
        ) from exc


def rotate_encrypted_value(value) -> str:
    """Re-encrypt a value using the first (current) key in the keyring."""

    plaintext = decrypt_value(value)
    if plaintext is None or plaintext == "":
        return plaintext
    current_key_id = configured_keyring()[0][0]
    if is_encrypted_value(value):
        stored_key_id = str(value)[len(ENCRYPTED_PREFIX) :].partition(":")[0]
        if stored_key_id == current_key_id:
            return str(value)
    return encrypt_value(plaintext)


class EncryptedTextField(models.TextField):
    """TextField that transparently stores authenticated ciphertext."""

    description = "Authenticated encrypted text"

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        if value is None or isinstance(value, str):
            return decrypt_value(value)
        return decrypt_value(str(value))

    def get_prep_value(self, value):
        if value is None:
            return None
        return encrypt_value(value)

    def value_to_string(self, obj):
        # Natural serializers/fixtures must never emit credential plaintext.
        return encrypt_value(self.value_from_object(obj))

