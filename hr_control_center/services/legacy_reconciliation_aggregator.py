"""Read-only orchestration of the existing HR15/HR16/HR18 cutover readers.

This module is deliberately an aggregator, not another reconciliation truth.
Each pair delegates to its owning domain service and only normalizes gate-level
status, drift counts and timing for cross-domain production acceptance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable


SCHEMA_VERSION = "hr.legacy-reconciliation-gate.2"
GLOBAL_SCHEMA_VERSION = "hr.legacy-reconciliation-global-gate.1"
DOMAIN_CHOICES = ("all", "hr15", "hr16", "hr18")
_NON_DRIFT_COUNT_KEYS = frozenset(
    {"matched", "legacyNonFinal", "nonAuthorityPreferenceAsset"}
)


class ReconciliationContractError(RuntimeError):
    """Raised when a domain reader violates the frozen aggregator contract."""


@dataclass(frozen=True)
class ReconciliationDomain:
    selector: str
    pair: str
    authority: str
    legacy_source_kind: str
    reader: Callable[[int, int], dict]


def _read_hr15(tenant_id: int, limit: int) -> dict:
    from hr_payroll.services.legacy_reconciliation_service import (
        LegacyPayrollReconciliationService,
    )

    return LegacyPayrollReconciliationService(tenant_id).snapshot(limit=limit)


def _read_hr16(tenant_id: int, limit: int) -> dict:
    from hr_exit.services.legacy_reconciliation_service import (
        LegacyExitReconciliationService,
    )

    return LegacyExitReconciliationService(tenant_id).snapshot(limit=limit)


def _read_hr18_asset(tenant_id: int, limit: int) -> dict:
    from hr_data.services.legacy_report_asset_service import (
        LegacyReportAssetInventoryService,
    )

    return LegacyReportAssetInventoryService(tenant_id).snapshot(limit=limit)


DOMAIN_REGISTRY = (
    ReconciliationDomain(
        selector="hr15",
        pair="HR15",
        authority="HR15",
        legacy_source_kind="DUAL_READ",
        reader=_read_hr15,
    ),
    ReconciliationDomain(
        selector="hr16",
        pair="HR16",
        authority="HR16",
        legacy_source_kind="DUAL_READ",
        reader=_read_hr16,
    ),
    ReconciliationDomain(
        selector="hr18",
        pair="HR18_ASSET",
        authority="HR18",
        legacy_source_kind="NON_AUTHORITY_ASSET_INVENTORY",
        reader=_read_hr18_asset,
    ),
)


def drift_count(snapshot: dict) -> int:
    """Count only unresolved reconciliation drift, never benign inventory."""
    counts = snapshot.get("counts") or {}
    try:
        return sum(
            int(value or 0)
            for key, value in counts.items()
            if key not in _NON_DRIFT_COUNT_KEYS
        )
    except (TypeError, ValueError) as exc:
        raise ReconciliationContractError(
            "domain reconciliation counts must be integer-compatible"
        ) from exc


def _validate_snapshot(spec: ReconciliationDomain, snapshot: dict) -> None:
    """Fail closed if an owning reader starts claiming a different truth."""
    if not isinstance(snapshot, dict):
        raise ReconciliationContractError(
            f"{spec.pair} reader must return a dictionary snapshot"
        )
    if snapshot.get("legacyAuthority") is not False:
        raise ReconciliationContractError(
            f"{spec.pair} legacy source must remain non-authoritative"
        )
    if snapshot.get("authority") != spec.authority:
        raise ReconciliationContractError(
            f"{spec.pair} authority changed: expected {spec.authority}, "
            f"got {snapshot.get('authority')!r}"
        )
    if snapshot.get("status") not in {"COMPLETE", "PARTIAL"}:
        raise ReconciliationContractError(
            f"{spec.pair} status must be COMPLETE or PARTIAL"
        )
    counts = snapshot.get("counts")
    if counts is not None and not isinstance(counts, dict):
        raise ReconciliationContractError(f"{spec.pair} counts must be a dictionary")


class LegacyReconciliationAggregator:
    """Aggregate existing domain snapshots for one explicit tenant.

    The aggregator has no model imports, no writes and no migration behavior.
    It is safe to reuse from the management command and the global Authority
    Gate without creating another source of HR truth.
    """

    def __init__(self, tenant_id: int, *, limit: int = 200):
        tenant_id = int(tenant_id or 0)
        if tenant_id <= 0:
            raise ValueError("tenant_id must be a positive integer")
        limit = int(limit)
        if not 1 <= limit <= 500:
            raise ValueError("limit must be in 1..500")
        self.tenant_id = tenant_id
        self.limit = limit

    @staticmethod
    def _selected(domain: str) -> tuple[ReconciliationDomain, ...]:
        domain = str(domain or "all").lower()
        if domain not in DOMAIN_CHOICES:
            raise ValueError(f"unsupported reconciliation domain: {domain}")
        if domain == "all":
            return DOMAIN_REGISTRY
        return tuple(spec for spec in DOMAIN_REGISTRY if spec.selector == domain)

    def run(self, *, domain: str = "all") -> dict:
        selected = self._selected(domain)
        started = time.monotonic()
        pairs: dict[str, dict] = {}
        durations: dict[str, float] = {}
        drift_by_pair: dict[str, int] = {}
        source_kinds: dict[str, str] = {}

        for spec in selected:
            pair_started = time.monotonic()
            snapshot = spec.reader(self.tenant_id, self.limit)
            _validate_snapshot(spec, snapshot)
            pairs[spec.pair] = snapshot
            durations[spec.pair] = round(time.monotonic() - pair_started, 6)
            drift_by_pair[spec.pair] = drift_count(snapshot)
            source_kinds[spec.pair] = spec.legacy_source_kind

        partial_pairs = [
            spec.pair
            for spec in selected
            if pairs[spec.pair].get("status") != "COMPLETE"
        ]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "tenantId": self.tenant_id,
            "status": "PARTIAL" if partial_pairs else "COMPLETE",
            "selectedPairs": [spec.pair for spec in selected],
            "partialPairs": partial_pairs,
            "reconciliationDriftTotal": sum(drift_by_pair.values()),
            "reconciliationDriftByPair": drift_by_pair,
            "reconciliationExecutionDurationSeconds": round(
                time.monotonic() - started,
                6,
            ),
            "pairExecutionDurationSeconds": durations,
            "legacySourceKinds": source_kinds,
            "orchestrationMode": "EXISTING_DOMAIN_READERS_ONLY",
            "pairs": pairs,
        }


class GlobalLegacyReconciliationAggregator:
    """Run the tenant-local aggregator across every school tenant.

    This layer never joins business facts across tenants. It only discovers
    Company primary keys, invokes the existing tenant aggregator one by one,
    and produces an acceptance summary. A deployment with zero tenants is
    intentionally ``EMPTY`` rather than green, so production acceptance cannot
    accidentally certify an unscoped or uninitialized database.
    """

    def __init__(self, *, limit: int = 200):
        limit = int(limit)
        if not 1 <= limit <= 500:
            raise ValueError("limit must be in 1..500")
        self.limit = limit

    @staticmethod
    def _normalize_tenant_ids(tenant_ids: Iterable[int]) -> tuple[int, ...]:
        normalized = sorted({int(value) for value in tenant_ids})
        if any(value <= 0 for value in normalized):
            raise ValueError("tenant ids must all be positive integers")
        return tuple(normalized)

    @classmethod
    def discover_tenant_ids(cls) -> tuple[int, ...]:
        from base.models import Company

        return cls._normalize_tenant_ids(
            Company.objects.order_by("pk").values_list("pk", flat=True)
        )

    def run(
        self,
        *,
        domain: str = "all",
        tenant_ids: Iterable[int] | None = None,
    ) -> dict:
        # Keep operator-input validation local to this orchestration layer.
        # The tenant aggregator is deliberately replaceable in tests and can
        # evolve internally without becoming part of the global contract.
        domain = str(domain or "all").lower()
        if domain not in DOMAIN_CHOICES:
            raise ValueError(f"unsupported reconciliation domain: {domain}")
        ids = (
            self.discover_tenant_ids()
            if tenant_ids is None
            else self._normalize_tenant_ids(tenant_ids)
        )
        started = time.monotonic()
        snapshots: dict[str, dict] = {}
        drift_by_tenant: dict[str, int] = {}
        partial_tenants: list[int] = []

        for tenant_id in ids:
            snapshot = LegacyReconciliationAggregator(
                tenant_id,
                limit=self.limit,
            ).run(domain=domain)
            snapshots[str(tenant_id)] = snapshot
            drift = int(snapshot.get("reconciliationDriftTotal") or 0)
            drift_by_tenant[str(tenant_id)] = drift
            if snapshot.get("status") != "COMPLETE":
                partial_tenants.append(tenant_id)

        if not ids:
            status = "EMPTY"
        elif partial_tenants:
            status = "PARTIAL"
        else:
            status = "COMPLETE"

        return {
            "schemaVersion": GLOBAL_SCHEMA_VERSION,
            "status": status,
            "tenantCount": len(ids),
            "tenantIds": list(ids),
            "partialTenantIds": partial_tenants,
            "reconciliationDriftTotal": sum(drift_by_tenant.values()),
            "reconciliationDriftByTenant": drift_by_tenant,
            "reconciliationExecutionDurationSeconds": round(
                time.monotonic() - started,
                6,
            ),
            "orchestrationMode": "TENANT_ISOLATED_EXISTING_DOMAIN_READERS_ONLY",
            "tenantSnapshots": snapshots,
        }
