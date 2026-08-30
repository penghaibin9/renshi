"""Trusted HR15 payment-provider registry.

The registry has no built-in success provider. Deployments must explicitly map
each ``provider_code`` to an adapter that owns dispatch authentication and
receipt verification. Missing or malformed configuration therefore fails
closed instead of advancing payment state.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.conf import settings
from django.utils.module_loading import import_string


class PaymentProviderRegistryError(Exception):
    pass


class PaymentProviderRegistry:
    SETTING = "HR15_PAYMENT_PROVIDERS"

    @classmethod
    def configured_paths(cls) -> dict[str, str]:
        configured = getattr(settings, cls.SETTING, {}) or {}
        if not isinstance(configured, Mapping):
            raise PaymentProviderRegistryError(
                f"{cls.SETTING} must be a provider-code to import-path mapping"
            )
        paths = {}
        for code, path in configured.items():
            normalized_code = str(code or "").strip().upper()
            normalized_path = str(path or "").strip()
            if normalized_code and normalized_path:
                paths[normalized_code] = normalized_path
        return paths

    @classmethod
    def resolve(cls, provider_code: str):
        code = str(provider_code or "").strip().upper()
        path = cls.configured_paths().get(code)
        if not path:
            raise PaymentProviderRegistryError(
                f"no trusted payment provider is configured for {code or '<blank>'}"
            )
        try:
            adapter = import_string(path)
            if isinstance(adapter, type):
                adapter = adapter()
        except Exception as exc:
            raise PaymentProviderRegistryError(
                f"trusted payment provider {code} cannot be loaded"
            ) from exc
        if not callable(getattr(adapter, "dispatch", None)) or not callable(
            getattr(adapter, "verify_receipt", None)
        ):
            raise PaymentProviderRegistryError(
                f"trusted payment provider {code} must implement dispatch and verify_receipt"
            )
        return adapter
