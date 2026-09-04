"""Authentication primitives for Meta WhatsApp webhooks."""

import hashlib
import hmac


def valid_webhook_signature(payload: bytes, signature: str, app_secrets) -> bool:
    """Validate ``X-Hub-Signature-256`` against one or more tenant secrets."""

    if not isinstance(payload, bytes) or not signature:
        return False
    algorithm, separator, supplied = str(signature).partition("=")
    if separator != "=" or algorithm.lower() != "sha256" or len(supplied) != 64:
        return False
    for secret in app_secrets:
        secret = str(secret or "")
        if not secret:
            continue
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, supplied.lower()):
            return True
    return False

