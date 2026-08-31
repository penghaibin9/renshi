"""Runtime HR01-HR18 Authority gate.

The gate validates existing module contracts, canonical routes and global
registries. It does not become another business Authority and performs no
writes. Optional legacy reconciliation delegates to the existing aggregators.
"""

from __future__ import annotations

from importlib import import_module

from django.apps import apps
from django.conf import settings
from django.urls import URLResolver, get_resolver

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import HR_DOMAINS, permission_registry
from horilla.hr_permissions import CANONICAL_PREFIX_ALIASES
from horilla.legacy_cutover_policy import legacy_cutover_policy_snapshot
from horilla.legacy_hr_cutover import (
    LEGACY_WRITE_ATTEMPTS_METRIC,
    RETIRED_LEGACY_HR_APPS,
    WRITE_SURFACE_REGISTRY,
    get_legacy_write_attempts_total,
)
from hr_control_center.services.legacy_reconciliation_aggregator import (
    GlobalLegacyReconciliationAggregator,
    LegacyReconciliationAggregator,
)


AUTHORITY_GATE_SCHEMA = "hr.authority-gate.3"
MODULE_CONTRACT_MODULES = (
    "hr_control_center.module_contract",
    "hr_structure.module_contract",
    "hr_staff.module_contract",
    "hr_recruitment.module_contract",
    "hr_onboarding.module_contract",
    "hr_changes.module_contract",
    "hr_contracts.module_contract",
    "hr_external.module_contract",
    "hr_qualification.module_contract",
    "hr10_development.module_contract",
    "hr_time.module_contract",
    "hr_assessment.module_contract",
    "hr_title.module_contract",
    "hr_appointment.module_contract",
    "hr_payroll.module_contract",
    "hr_exit.module_contract",
    "hr_self.module_contract",
    "hr_data.module_contract",
)
_REQUIRED_SEMANTIC_WRITE_SURFACES = (
    "update-kanban-sequence",
    "update-kanban-item-group",
    "update-kanban-group-sequence",
    "history-revert",
    "generic-history-revert",
    "dynamic-form",
    "dynamic-bulk-update",
    "dynamic-import",
    "orm-resolved-write",
)
_EVENT_OPTIONAL_MODULES = frozenset({"HR01", "HR17"})


def load_module_contracts() -> tuple[dict, ...]:
    """Load all 18 module boundary contracts in HR code order."""
    contracts = []
    for index, module_path in enumerate(MODULE_CONTRACT_MODULES, start=1):
        module = import_module(module_path)
        expected_code = f"HR{index:02d}"
        code = getattr(module, "MODULE_CODE", "")
        app_label = getattr(module, "APP_LABEL", module_path.split(".", 1)[0])
        api_prefix = getattr(
            module,
            "CANONICAL_API_PREFIX",
            getattr(module, "CANONICAL_API_ROOT", ""),
        )
        permission_prefix = getattr(
            module,
            "PERMISSION_PREFIX",
            f"hr.{HR_DOMAINS.get(code, '')}" if code in HR_DOMAINS else "",
        )
        authority_kind = getattr(module, "AUTHORITY_KIND", "")
        owns = tuple(getattr(module, "OWNS", ()))
        contracts.append(
            {
                "expectedCode": expected_code,
                "moduleCode": code,
                "modulePath": module_path,
                "appLabel": app_label,
                "canonicalApiPrefix": str(api_prefix or ""),
                "permissionPrefix": str(permission_prefix or ""),
                "authorityKind": str(authority_kind or ""),
                "owns": owns,
                "module": module,
            }
        )
    return tuple(contracts)


def _route_text(pattern) -> str:
    route = getattr(pattern.pattern, "_route", None)
    return str(route if route is not None else pattern.pattern)


def _walk_urlpatterns(patterns, prefix=""):
    for entry in patterns:
        route = f"{prefix}{_route_text(entry)}"
        if isinstance(entry, URLResolver):
            yield from _walk_urlpatterns(entry.url_patterns, route)
            continue
        callback = entry.callback
        callback_module = str(getattr(callback, "__module__", "") or "")
        callback_name = str(
            getattr(callback, "__qualname__", getattr(callback, "__name__", "")) or ""
        )
        yield route, callback_module, f"{callback_module}.{callback_name}".strip(".")


def _normalize_route(value: str) -> str:
    value = str(value or "").replace("^", "")
    return value.lstrip("/")


def _duplicate_canonical_routes(routes) -> dict[str, tuple[str, ...]]:
    callbacks_by_route: dict[str, set[str]] = {}
    for route, _callback_module, callback_identity in routes:
        normalized = _normalize_route(route).rstrip("/")
        if not normalized.startswith("api/v1/hr/"):
            continue
        callbacks_by_route.setdefault(normalized, set()).add(callback_identity)
    return {
        route: tuple(sorted(callbacks))
        for route, callbacks in sorted(callbacks_by_route.items())
        if len(callbacks) > 1
    }


class AuthorityGateService:
    def __init__(
        self,
        *,
        tenant_id: int | None = None,
        all_tenants: bool = False,
        limit: int = 200,
    ):
        if tenant_id is not None and all_tenants:
            raise ValueError("tenant_id and all_tenants are mutually exclusive")
        self.tenant_id = int(tenant_id) if tenant_id is not None else None
        self.all_tenants = bool(all_tenants)
        self.limit = int(limit)

    @staticmethod
    def _registry_counts(definitions) -> dict[str, int]:
        counts = {code: 0 for code in HR_DOMAINS}
        for definition in definitions:
            code = getattr(definition, "module_code", "")
            if code in counts:
                counts[code] += 1
        return counts

    def run(
        self,
        *,
        require_reconciliation: bool = False,
        require_zero_legacy_writes: bool = False,
    ) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        contracts = load_module_contracts()
        expected_codes = tuple(f"HR{i:02d}" for i in range(1, 19))

        if tuple(HR_DOMAINS) != expected_codes:
            errors.append("HR_DOMAINS must cover HR01-HR18 exactly")
        if len(contracts) != 18:
            errors.append("module contract registry must contain exactly 18 modules")

        routes = tuple(_walk_urlpatterns(get_resolver().url_patterns))
        module_rows = []
        for contract in contracts:
            code = contract["moduleCode"]
            expected_code = contract["expectedCode"]
            app_label = contract["appLabel"]
            domain = HR_DOMAINS.get(expected_code, "")
            expected_permission = f"hr.{domain}"
            api_prefix = contract["canonicalApiPrefix"]

            if code != expected_code:
                errors.append(
                    f"{contract['modulePath']} code mismatch: {code!r} != {expected_code}"
                )
            if not apps.is_installed(app_label):
                errors.append(f"{expected_code} app is not installed: {app_label}")
            if not api_prefix.startswith("/api/v1/hr"):
                errors.append(
                    f"{expected_code} canonical API escaped /api/v1/hr: {api_prefix!r}"
                )
            if contract["permissionPrefix"] != expected_permission:
                errors.append(
                    f"{expected_code} permission prefix mismatch: "
                    f"{contract['permissionPrefix']!r} != {expected_permission!r}"
                )
            if not contract["authorityKind"] and not contract["owns"]:
                errors.append(f"{expected_code} has no machine-readable Authority boundary")

            normalized_prefix = _normalize_route(api_prefix).rstrip("/")
            callback_routes = [
                route
                for route, callback_module, _callback_identity in routes
                if _normalize_route(route).startswith(normalized_prefix)
                and (
                    callback_module == app_label
                    or callback_module.startswith(f"{app_label}.")
                )
            ]
            if not callback_routes:
                errors.append(
                    f"{expected_code} has no canonical API callback under {api_prefix}"
                )

            module_rows.append(
                {
                    "moduleCode": expected_code,
                    "appLabel": app_label,
                    "canonicalApiPrefix": api_prefix,
                    "permissionPrefix": contract["permissionPrefix"],
                    "authorityKind": contract["authorityKind"] or "DECLARED_OWNS",
                    "canonicalApiCallbackCount": len(callback_routes),
                }
            )

        expected_aliases = {
            f"hr{i:02d}.": f"hr.{HR_DOMAINS[f'HR{i:02d}']}."
            for i in range(1, 19)
        }
        if CANONICAL_PREFIX_ALIASES != expected_aliases:
            errors.append("canonical permission aliases diverged from HR01-HR18 domains")

        permission_counts = self._registry_counts(permission_registry.all())
        event_counts = self._registry_counts(global_event_registry.all())
        for code in expected_codes:
            if permission_counts[code] == 0:
                errors.append(f"{code} has no registered canonical permission definitions")
            if code not in _EVENT_OPTIONAL_MODULES and event_counts[code] == 0:
                errors.append(f"{code} has no registered canonical business events")
        for row in module_rows:
            code = row["moduleCode"]
            row["permissionDefinitionCount"] = permission_counts[code]
            row["eventDefinitionCount"] = event_counts[code]

        duplicate_routes = _duplicate_canonical_routes(routes)
        for route, callbacks in duplicate_routes.items():
            errors.append(
                f"duplicate canonical route has different callbacks: /{route}/ -> "
                + ", ".join(callbacks)
            )

        legacy_policy = legacy_cutover_policy_snapshot()
        if legacy_policy.get("formalWriterRollbackAllowed") is not False:
            errors.append("legacy formal writer rollback must remain forbidden")
        if legacy_policy.get("rollbackMode") != "ENTRY_ADAPTER_ONLY":
            errors.append("legacy rollback mode must remain ENTRY_ADAPTER_ONLY")
        if RETIRED_LEGACY_HR_APPS != frozenset({"payroll", "offboarding", "report"}):
            errors.append("retired legacy HR app set changed unexpectedly")

        for surface in _REQUIRED_SEMANTIC_WRITE_SURFACES:
            if not WRITE_SURFACE_REGISTRY.get(surface, {}).get("semantic_write"):
                errors.append(f"semantic write surface is not sealed: {surface}")

        routers = set(getattr(settings, "DATABASE_ROUTERS", ()))
        if "horilla.legacy_hr_cutover.LegacyWriteAuthorityRouter" not in routers:
            errors.append("final resolved-model legacy write router is not installed")
        middleware = set(getattr(settings, "MIDDLEWARE", ()))
        if "horilla.legacy_hr_cutover.LegacyWriteAuthorityMiddleware" not in middleware:
            errors.append("legacy write 410 exception middleware is not installed")
        if "horilla.horilla_middlewares.ThreadLocalMiddleware" not in middleware:
            errors.append("request context cleanup middleware is not installed")

        legacy_write_attempts = get_legacy_write_attempts_total()
        if require_zero_legacy_writes and legacy_write_attempts != 0:
            errors.append(
                f"{LEGACY_WRITE_ATTEMPTS_METRIC} must be zero, got {legacy_write_attempts}"
            )

        reconciliation = {"status": "NOT_RUN"}
        if self.all_tenants:
            reconciliation = GlobalLegacyReconciliationAggregator(
                limit=self.limit
            ).run(domain="all")
            if reconciliation["status"] != "COMPLETE":
                errors.append(
                    "global legacy reconciliation is not COMPLETE: "
                    f"{reconciliation['status']}"
                )
        elif self.tenant_id is not None:
            reconciliation = LegacyReconciliationAggregator(
                self.tenant_id,
                limit=self.limit,
            ).run(domain="all")
            if reconciliation["status"] != "COMPLETE":
                errors.append(
                    "legacy reconciliation is PARTIAL: "
                    + ",".join(reconciliation["partialPairs"])
                )
        elif require_reconciliation:
            errors.append(
                "production Authority Gate requires --tenant or --all-tenants"
            )

        return {
            "schemaVersion": AUTHORITY_GATE_SCHEMA,
            "status": "PARTIAL" if errors else "COMPLETE",
            "errors": errors,
            "warnings": warnings,
            "modules": module_rows,
            "permissionDefinitionCountByModule": permission_counts,
            "eventDefinitionCountByModule": event_counts,
            "duplicateCanonicalRoutes": duplicate_routes,
            "legacyCutoverPolicy": legacy_policy,
            "legacyWriteAttemptMetric": {
                "name": LEGACY_WRITE_ATTEMPTS_METRIC,
                "total": legacy_write_attempts,
                "counter": "shared-cache-best-effort",
                "authoritativeEvidence": "structured-legacy-cutover-log",
            },
            "reconciliation": reconciliation,
        }
