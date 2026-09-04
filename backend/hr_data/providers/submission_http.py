"""Configured HTTPS boundary for HR18 formal submission dispatch.

The durable queue and retry policy live in ``SubmissionDispatchService``.  This
adapter performs one bounded network call and verifies signed asynchronous
receipts.  Secrets, endpoint query strings and response bodies are never
included in raised errors or durable job records.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from urllib.parse import urlparse

import requests
from django.conf import settings


class SubmissionHttpAdapterError(RuntimeError):
    """Secret-free provider/configuration failure."""


def _canonical(value: Mapping) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _configuration() -> tuple[str, str, float, str, str, str]:
    endpoint = str(
        getattr(settings, "HR18_SUBMISSION_HTTP_ENDPOINT", "") or ""
    ).strip()
    token = str(getattr(settings, "HR18_SUBMISSION_HTTP_TOKEN", "") or "").strip()
    secret = str(
        getattr(settings, "HR18_SUBMISSION_RECEIPT_HMAC_SECRET", "") or ""
    ).strip()
    key_id = str(
        getattr(settings, "HR18_SUBMISSION_RECEIPT_KEY_ID", "") or ""
    ).strip()
    provider_version = str(
        getattr(settings, "HR18_SUBMISSION_HTTP_PROVIDER_VERSION", "https-v1")
        or ""
    ).strip()
    try:
        timeout = float(
            getattr(settings, "HR18_SUBMISSION_HTTP_TIMEOUT_SECONDS", 15)
        )
    except (TypeError, ValueError) as exc:
        raise SubmissionHttpAdapterError("submission timeout is invalid") from exc

    parsed = urlparse(endpoint)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not endpoint
        or not parsed.hostname
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme != "https" and not (settings.DEBUG and loopback))
    ):
        raise SubmissionHttpAdapterError(
            "submission endpoint must use HTTPS (HTTP loopback is development-only)"
        )
    if not token:
        raise SubmissionHttpAdapterError("submission provider token is not configured")
    if not secret or len(secret.encode("utf-8")) < 32:
        raise SubmissionHttpAdapterError(
            "submission receipt HMAC secret must contain at least 32 bytes"
        )
    if not key_id or len(key_id) > 128:
        raise SubmissionHttpAdapterError("submission receipt key id is invalid")
    if not provider_version or len(provider_version) > 64:
        raise SubmissionHttpAdapterError("submission provider version is invalid")
    if not 1 <= timeout <= 60:
        raise SubmissionHttpAdapterError("submission timeout must be between 1 and 60 seconds")
    return endpoint, token, timeout, secret, key_id, provider_version


class HttpsSubmissionAdapter:
    """Dispatch frozen manifests and verify HMAC-SHA256 provider receipts."""

    def dispatch(
        self,
        *,
        tenant_id,
        submission_manifest,
        idempotency_key,
        actor_user_id=None,
    ):
        endpoint, token, timeout, _secret, _key_id, provider_version = _configuration()
        payload = {
            "schemaVersion": "hr18.submission-dispatch.request.1",
            "tenantId": int(tenant_id),
            "actorUserId": actor_user_id,
            "idempotencyKey": idempotency_key,
            "submission": dict(submission_manifest),
        }
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
                json=payload,
                timeout=timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise SubmissionHttpAdapterError(
                "submission provider is temporarily unavailable"
            ) from exc
        except requests.RequestException as exc:
            raise SubmissionHttpAdapterError("submission provider transport failed") from exc

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise SubmissionHttpAdapterError(
                f"submission provider is temporarily unavailable (HTTP {response.status_code})"
            )
        if not 200 <= response.status_code < 300:
            raise SubmissionHttpAdapterError(
                f"submission provider rejected the request (HTTP {response.status_code})"
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise SubmissionHttpAdapterError(
                "submission provider returned invalid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise SubmissionHttpAdapterError(
                "submission provider response must be a JSON object"
            )
        result = decoded.get("data", decoded)
        if not isinstance(result, Mapping):
            raise SubmissionHttpAdapterError(
                "submission provider dispatch result must be an object"
            )
        # The authority service independently verifies all frozen identity
        # fields.  The configured version is a safe fallback for providers
        # that intentionally omit a release label.
        return {**dict(result), "providerVersion": result.get("providerVersion") or provider_version}

    def verify_receipt(self, *, tenant_id, submission_manifest, receipt_payload):
        _endpoint, _token, _timeout, secret, key_id, provider_version = _configuration()
        if not isinstance(receipt_payload, Mapping):
            raise SubmissionHttpAdapterError("provider receipt must be an object")
        receipt = dict(receipt_payload)
        signature = str(receipt.pop("signature", "") or "").strip().lower()
        supplied_hash = str(receipt.pop("receiptHash", "") or "").strip().lower()
        if len(signature) != 64 or any(char not in "0123456789abcdef" for char in signature):
            raise SubmissionHttpAdapterError("provider receipt signature is invalid")

        calculated_hash = hashlib.sha256(
            _canonical(receipt).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(calculated_hash, supplied_hash):
            raise SubmissionHttpAdapterError("provider receipt hash is invalid")
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            calculated_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise SubmissionHttpAdapterError("provider receipt signature is invalid")
        if str(receipt.get("signatureKeyId") or "").strip() != key_id:
            raise SubmissionHttpAdapterError("provider receipt key id is invalid")

        expected = {
            "tenantId": int(tenant_id),
            "submissionId": str(submission_manifest.get("submissionId") or ""),
            "schemaVersion": str(submission_manifest.get("schemaVersion") or ""),
            "definitionVersion": int(submission_manifest.get("definitionVersion")),
            "payloadHash": str(submission_manifest.get("payloadHash") or "").lower(),
        }
        for field, value in expected.items():
            candidate = receipt.get(field)
            if field in {"tenantId", "definitionVersion"}:
                try:
                    candidate = int(candidate)
                except (TypeError, ValueError):
                    candidate = None
            else:
                candidate = str(candidate or "")
            if candidate != value:
                raise SubmissionHttpAdapterError(
                    f"provider receipt has mismatched {field}"
                )
        outcome = str(receipt.get("signedOutcome") or "").strip().upper()
        if outcome not in {"ACCEPTED", "REJECTED"}:
            raise SubmissionHttpAdapterError("provider receipt outcome is invalid")
        receipt_ref = str(receipt.get("receiptRef") or "").strip()
        dispatch_ref = str(receipt.get("dispatchRef") or "").strip()
        if not receipt_ref or len(receipt_ref) > 255 or not dispatch_ref:
            raise SubmissionHttpAdapterError("provider receipt reference is invalid")

        return {
            "verified": True,
            **expected,
            "dispatchRef": dispatch_ref,
            "accepted": outcome == "ACCEPTED",
            "receiptRef": receipt_ref,
            "providerVersion": str(receipt.get("providerVersion") or provider_version),
            "receiptHash": calculated_hash,
            "signatureKeyId": key_id,
        }
