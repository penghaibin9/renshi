"""Configured HTTP boundary shared by HR08 external-system providers."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings

from hr_external.integrations.base import BaseProvider, ProviderResult, ProviderStatus


class ConfiguredJsonProvider(BaseProvider):
    """Fail-closed JSON transport with bounded timeouts and receipt checks."""

    settings_name = ""
    source_version = "v1"

    def __init__(self, *, config: dict | None = None, session=None):
        self._config_override = config
        self._session = session or requests.Session()

    @property
    def config(self) -> dict:
        if self._config_override is not None:
            return dict(self._config_override)
        configured = getattr(settings, self.settings_name, {}) if self.settings_name else {}
        return dict(configured) if isinstance(configured, dict) else {}

    def _request(
        self,
        *,
        tenant_id: int,
        method: str,
        path: str,
        idempotency_key: str = "",
        payload: dict | None = None,
        params: dict | None = None,
        receipt_required: bool = False,
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        config = self.config
        base_url = str(config.get("BASE_URL", "")).strip()
        token = str(config.get("TOKEN", "")).strip()
        if not base_url or not token:
            return self.unavailable(
                "PROVIDER_UNAVAILABLE",
                f"{self.owner_domain} provider is not configured",
                source_version=self.source_version,
            )
        parsed = urlsplit(base_url)
        loopback_debug = settings.DEBUG and parsed.hostname in {
            "127.0.0.1", "localhost", "::1"
        }
        if (
            (parsed.scheme != "https" and not loopback_debug)
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_code="PROVIDER_CONFIG_INVALID",
                error_message=f"{self.owner_domain} provider requires a valid HTTPS URL",
                source_version=self.source_version,
            )
        if receipt_required and not idempotency_key:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_code="IDEMPOTENCY_KEY_REQUIRED",
                error_message="Write operations require an idempotency key",
                source_version=self.source_version,
            )

        try:
            timeout_ms = int(config.get("TIMEOUT_MS", self.default_timeout_ms))
        except (TypeError, ValueError):
            timeout_ms = self.default_timeout_ms
        timeout_seconds = max(0.1, min(timeout_ms, 30_000) / 1000)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Tenant-ID": str(tenant_id),
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        try:
            response = self._session.request(
                method=method,
                url=urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
                headers=headers,
                json=payload,
                params=params,
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            return self.unavailable(
                "PROVIDER_TIMEOUT",
                f"{self.owner_domain} provider timed out",
                source_version=self.source_version,
            )
        except requests.RequestException:
            return self.unavailable(
                "PROVIDER_TRANSPORT_ERROR",
                f"{self.owner_domain} provider transport failed",
                source_version=self.source_version,
            )

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            return self.unavailable(
                "PROVIDER_RETRYABLE",
                f"{self.owner_domain} provider returned {response.status_code}",
                source_version=self.source_version,
            )
        if not 200 <= response.status_code < 300:
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_code="PROVIDER_REJECTED",
                error_message=f"{self.owner_domain} provider returned {response.status_code}",
                source_version=self.source_version,
            )
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_code="PROVIDER_RESPONSE_INVALID",
                error_message="Provider response must be a JSON object",
                source_version=self.source_version,
            )
        if receipt_required and not str(data.get("receiptId", "")).strip():
            return ProviderResult(
                status=ProviderStatus.ERROR,
                error_code="PROVIDER_RECEIPT_INVALID",
                error_message="Provider write response is missing receiptId",
                source_version=self.source_version,
            )
        return ProviderResult(
            status=ProviderStatus.OK,
            data=data,
            source_version=str(data.get("sourceVersion") or self.source_version),
            source_updated_at=data.get("sourceUpdatedAt"),
        )
