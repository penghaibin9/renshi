"""Configured HTTPS transport for frozen HR18 exchange datasets."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

import requests
from django.conf import settings


class ExchangeHttpProviderError(RuntimeError):
    """Secret-free exchange transport/configuration failure."""


def _configuration() -> tuple[str, str, float, str]:
    endpoint = str(getattr(settings, "HR18_EXCHANGE_HTTP_ENDPOINT", "") or "").strip()
    token = str(getattr(settings, "HR18_EXCHANGE_HTTP_TOKEN", "") or "").strip()
    version = str(
        getattr(settings, "HR18_EXCHANGE_HTTP_PROVIDER_VERSION", "https-v1") or ""
    ).strip()
    try:
        timeout = float(getattr(settings, "HR18_EXCHANGE_HTTP_TIMEOUT_SECONDS", 15))
    except (TypeError, ValueError) as exc:
        raise ExchangeHttpProviderError("exchange timeout is invalid") from exc
    parsed = urlparse(endpoint)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not endpoint
        or not parsed.hostname
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme != "https" and not (settings.DEBUG and loopback))
    ):
        raise ExchangeHttpProviderError(
            "exchange endpoint must use HTTPS (HTTP loopback is development-only)"
        )
    if not token:
        raise ExchangeHttpProviderError("exchange provider token is not configured")
    if not version or len(version) > 64:
        raise ExchangeHttpProviderError("exchange provider version is invalid")
    if not 1 <= timeout <= 60:
        raise ExchangeHttpProviderError("exchange timeout must be between 1 and 60 seconds")
    return endpoint, token, timeout, version


def https_exchange_provider(
    *,
    tenant_id,
    job,
    dataset,
    target_mapping,
    idempotency_key,
    actor_user_id=None,
):
    """Transmit one immutable dataset manifest to the configured target."""
    endpoint, token, timeout, configured_version = _configuration()
    payload = {
        "schemaVersion": "hr18.exchange-dispatch.request.1",
        "tenantId": int(tenant_id),
        "actorUserId": actor_user_id,
        "idempotencyKey": idempotency_key,
        "job": {
            "id": str(job.id),
            "jobNo": job.job_no,
            "snapshotHash": job.snapshot_hash,
        },
        "dataset": {
            "id": str(dataset.id),
            "datasetCode": dataset.dataset_code,
            "versionNo": dataset.version_no,
            "schema": dataset.schema_json,
            "sourceSnapshot": dataset.source_snapshot_json,
            "payloadRef": dataset.payload_ref,
            "payloadHash": dataset.payload_hash,
            "recordCount": dataset.record_count,
            "frozenAt": dataset.frozen_at.isoformat(),
        },
        "target": {
            "id": str(target_mapping.id),
            "targetCode": target_mapping.target_code,
            "versionNo": target_mapping.version_no,
            "transportKind": target_mapping.transport_kind,
            "mapping": target_mapping.mapping_json,
            "expectedReceipt": target_mapping.expected_receipt,
        },
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
        raise ExchangeHttpProviderError(
            "exchange provider is temporarily unavailable"
        ) from exc
    except requests.RequestException as exc:
        raise ExchangeHttpProviderError("exchange provider transport failed") from exc
    if response.status_code in {408, 425, 429} or response.status_code >= 500:
        raise ExchangeHttpProviderError(
            f"exchange provider is temporarily unavailable (HTTP {response.status_code})"
        )
    if not 200 <= response.status_code < 300:
        raise ExchangeHttpProviderError(
            f"exchange provider rejected the request (HTTP {response.status_code})"
        )
    try:
        decoded = response.json()
    except ValueError as exc:
        raise ExchangeHttpProviderError("exchange provider returned invalid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ExchangeHttpProviderError("exchange provider response must be an object")
    result = decoded.get("data", decoded)
    if not isinstance(result, Mapping):
        raise ExchangeHttpProviderError("exchange provider result must be an object")
    return {
        **dict(result),
        "providerVersion": result.get("providerVersion") or configured_version,
    }
