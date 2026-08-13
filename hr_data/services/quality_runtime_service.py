"""Production runtime registry for HR18 data-quality execution.

The core execution service remains registry-agnostic for tests and extensions.
This runtime layer provides a small built-in HR03 quality adapter while still
allowing deployment settings to override or add source-domain providers.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.conf import settings

from hr_data.services.quality_service import DataQualityError, DataQualityExecutionService


class RuntimeDataQualityExecutionService(DataQualityExecutionService):
    _BUILTIN_PROVIDERS = {
        "HR03": "hr_data.providers.hr03_quality.quality_provider",
    }

    @staticmethod
    def _registry() -> Mapping:
        configured = getattr(settings, "HR18_QUALITY_PROVIDERS", {})
        if not isinstance(configured, Mapping):
            raise DataQualityError(
                "QUALITY_PROVIDER_REGISTRY_INVALID",
                "HR18_QUALITY_PROVIDERS must be a mapping",
            )
        registry = dict(RuntimeDataQualityExecutionService._BUILTIN_PROVIDERS)
        for domain, provider_path in configured.items():
            domain = str(domain or "").strip().upper()
            if domain:
                registry[domain] = provider_path
        return registry
