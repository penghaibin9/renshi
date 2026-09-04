"""One-way storage for high-entropy bearer and single-use tokens."""

from __future__ import annotations

import hashlib


TOKEN_DIGEST_PREFIX = "sha256$"


def bearer_token_digest(raw_token, *, namespace: str) -> str:
    value = str(raw_token or "")
    if value.startswith(TOKEN_DIGEST_PREFIX) and len(value) == 71:
        return value
    domain = str(namespace or "").strip().encode("utf-8")
    return TOKEN_DIGEST_PREFIX + hashlib.sha256(
        b"renshi:bearer-token:v1:" + domain + b":" + value.encode("utf-8")
    ).hexdigest()
