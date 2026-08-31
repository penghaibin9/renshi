"""Trusted payroll-input provider registry.

There is deliberately no implicit success provider.  Every authority used to
freeze payroll input must be mapped by deployment configuration so a missing
HR03/HR11/HR12/HR14 boundary cannot silently turn into caller-supplied facts.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.conf import settings
from django.utils.module_loading import import_string


REQUIRED_INPUT_AUTHORITIES = frozenset({"HR03", "HR11", "HR12", "HR14"})


class PayrollInputProviderRegistryError(Exception):
    pass


class PayrollInputProviderRegistry:
    SETTING = "HR15_PAYROLL_INPUT_PROVIDERS"

    @classmethod
    def configured_paths(cls) -> dict[str, str]:
        configured = getattr(settings, cls.SETTING, {}) or {}
        if not isinstance(configured, Mapping):
            raise PayrollInputProviderRegistryError(
                f"{cls.SETTING} must be an authority-code to import-path mapping"
            )
        paths: dict[str, str] = {}
        for authority, path in configured.items():
            code = str(authority or "").strip().upper()
            import_path = str(path or "").strip()
            if not code or not import_path:
                raise PayrollInputProviderRegistryError(
                    f"{cls.SETTING} contains a blank authority or provider path"
                )
            paths[code] = import_path
        missing = sorted(REQUIRED_INPUT_AUTHORITIES - set(paths))
        if missing:
            raise PayrollInputProviderRegistryError(
                "trusted payroll input providers are missing: " + ",".join(missing)
            )
        return paths

    @classmethod
    def resolve_all(cls) -> tuple[tuple[str, object], ...]:
        providers = []
        for authority, path in sorted(cls.configured_paths().items()):
            try:
                adapter = import_string(path)
                if isinstance(adapter, type):
                    adapter = adapter()
            except Exception as exc:
                raise PayrollInputProviderRegistryError(
                    f"trusted payroll input provider {authority} cannot be loaded"
                ) from exc
            if not callable(getattr(adapter, "collect", None)):
                raise PayrollInputProviderRegistryError(
                    f"trusted payroll input provider {authority} must implement collect"
                )
            providers.append((authority, adapter))
        return tuple(providers)
