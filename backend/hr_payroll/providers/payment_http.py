"""Authenticated HTTPS payment dispatch and signed receipt verification.

No bank is treated as successful locally. Dispatch identity is revalidated by
``PayrollPaymentService`` and terminal receipts must carry an HMAC-SHA256 seal
from the configured finance gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from urllib.parse import urlparse

import requests
from django.conf import settings


class PaymentHttpProviderError(RuntimeError):
    """Secret-free configuration, transport or signature failure."""


def _canonical(value: Mapping) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _configuration() -> tuple[str, str, float, str, str, str]:
    endpoint = str(getattr(settings, "HR15_PAYMENT_HTTP_ENDPOINT", "") or "").strip()
    token = str(getattr(settings, "HR15_PAYMENT_HTTP_TOKEN", "") or "").strip()
    secret = str(
        getattr(settings, "HR15_PAYMENT_RECEIPT_HMAC_SECRET", "") or ""
    ).strip()
    key_id = str(
        getattr(settings, "HR15_PAYMENT_RECEIPT_KEY_ID", "") or ""
    ).strip()
    provider_code = str(
        getattr(settings, "HR15_PAYMENT_PROVIDER_CODE", "") or ""
    ).strip().upper()
    try:
        timeout = float(getattr(settings, "HR15_PAYMENT_HTTP_TIMEOUT_SECONDS", 15))
    except (TypeError, ValueError) as exc:
        raise PaymentHttpProviderError("payment timeout is invalid") from exc

    parsed = urlparse(endpoint)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not endpoint
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme != "https" and not (settings.DEBUG and loopback))
    ):
        raise PaymentHttpProviderError(
            "payment endpoint must use HTTPS (HTTP loopback is development-only)"
        )
    if not token or len(token) < 16:
        raise PaymentHttpProviderError("payment provider token is not configured")
    if not secret or len(secret.encode("utf-8")) < 32:
        raise PaymentHttpProviderError(
            "payment receipt HMAC secret must contain at least 32 bytes"
        )
    if not key_id or len(key_id) > 128:
        raise PaymentHttpProviderError("payment receipt key id is invalid")
    if (
        not provider_code
        or len(provider_code) > 64
        or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in provider_code)
    ):
        raise PaymentHttpProviderError("payment provider code is invalid")
    if not 1 <= timeout <= 60:
        raise PaymentHttpProviderError("payment timeout must be between 1 and 60 seconds")
    return endpoint, token, timeout, secret, key_id, provider_code


class HttpsPaymentProvider:
    """Send one idempotent instruction and authenticate asynchronous receipts."""

    def dispatch(self, request):
        if not isinstance(request, Mapping):
            raise PaymentHttpProviderError("payment request must be an object")
        endpoint, token, timeout, _secret, _key_id, provider_code = _configuration()
        if str(request.get("providerCode") or "").strip().upper() != provider_code:
            raise PaymentHttpProviderError("payment request provider code is invalid")
        idempotency_key = str(request.get("idempotencyKey") or "").strip()
        tenant_id = request.get("tenantId")
        if not idempotency_key or tenant_id in {None, ""}:
            raise PaymentHttpProviderError("payment request identity is incomplete")
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                    "X-Tenant-ID": str(int(tenant_id)),
                },
                json={
                    "schemaVersion": "hr15.payment-dispatch.request.1",
                    "paymentInstruction": dict(request),
                },
                timeout=timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise PaymentHttpProviderError(
                "payment provider is temporarily unavailable"
            ) from exc
        except requests.RequestException as exc:
            raise PaymentHttpProviderError("payment provider transport failed") from exc

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise PaymentHttpProviderError(
                f"payment provider is temporarily unavailable (HTTP {response.status_code})"
            )
        if not 200 <= response.status_code < 300:
            raise PaymentHttpProviderError(
                f"payment provider rejected the request (HTTP {response.status_code})"
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise PaymentHttpProviderError("payment provider returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise PaymentHttpProviderError("payment provider response must be an object")
        result = decoded.get("data", decoded)
        if not isinstance(result, Mapping):
            raise PaymentHttpProviderError("payment dispatch result must be an object")
        return dict(result)

    def verify_receipt(self, payload):
        _endpoint, _token, _timeout, secret, key_id, provider_code = _configuration()
        if not isinstance(payload, Mapping):
            raise PaymentHttpProviderError("payment receipt must be an object")
        receipt = dict(payload)
        signature = str(receipt.pop("signature", "") or "").strip().lower()
        supplied_hash = str(receipt.pop("receiptHash", "") or "").strip().lower()
        if len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature):
            raise PaymentHttpProviderError("payment receipt signature is invalid")
        if len(supplied_hash) != 64 or any(c not in "0123456789abcdef" for c in supplied_hash):
            raise PaymentHttpProviderError("payment receipt hash is invalid")
        calculated_hash = hashlib.sha256(
            _canonical(receipt).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(calculated_hash, supplied_hash):
            raise PaymentHttpProviderError("payment receipt hash is invalid")
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            calculated_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise PaymentHttpProviderError("payment receipt signature is invalid")
        if str(receipt.get("signatureKeyId") or "").strip() != key_id:
            raise PaymentHttpProviderError("payment receipt key id is invalid")
        if str(receipt.get("providerCode") or "").strip().upper() != provider_code:
            raise PaymentHttpProviderError("payment receipt provider code is invalid")
        # Signature metadata is not part of the normalized HR15 business
        # receipt; its hash and key id remain in the durable provider payload
        # supplied to the worker/audit transport.
        receipt.pop("signatureKeyId", None)
        return receipt
