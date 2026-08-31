"""HR18 typed Provider/source-status propagation.

The data center must never normalize ``UNAVAILABLE``/``ERROR`` to numeric zero
or label incomplete data as complete.  Metric calculation itself will be added
behind a typed DSL later; this module first freezes the source-trust contract
used by every future metric/report/submission path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping, Optional


class SourceStatus(StrEnum):
    OK = "OK"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class MetricSourceGateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ProviderSnapshot:
    domain: str
    status: SourceStatus
    value: Any = None
    source_updated_at: Optional[datetime] = None
    source_version: str = ""
    details: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class MetricSourceGateResult:
    status: SourceStatus
    value: Any
    complete: bool
    required_domains: tuple[str, ...]
    source_statuses: Mapping[str, str]
    blocked_domains: tuple[str, ...] = ()


class MetricSourceGate:
    """Propagate required Provider statuses without evaluating metric formulas."""

    _BLOCKING = {SourceStatus.UNAVAILABLE, SourceStatus.ERROR}

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise MetricSourceGateError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id

    def evaluate(
        self,
        *,
        metric_definition,
        proposed_value: Any,
        provider_snapshots: Iterable[ProviderSnapshot],
    ) -> MetricSourceGateResult:
        if getattr(metric_definition, "tenant_id", None) != self.tenant_id:
            raise MetricSourceGateError(
                "METRIC_DEFINITION_CROSS_TENANT",
                "metric definition does not belong to tenant",
            )

        required = tuple(dict.fromkeys(getattr(metric_definition, "source_domains", []) or []))
        snapshots = {snapshot.domain: snapshot for snapshot in provider_snapshots}

        missing = [domain for domain in required if domain not in snapshots]
        blocking = [
            domain
            for domain in required
            if domain in snapshots and snapshots[domain].status in self._BLOCKING
        ]
        blocked = tuple(missing + [domain for domain in blocking if domain not in missing])
        statuses = {
            domain: (
                snapshots[domain].status.value
                if domain in snapshots
                else SourceStatus.UNAVAILABLE.value
            )
            for domain in required
        }

        # Missing/error/unavailable sources make the metric unavailable.  The
        # caller's proposed value is discarded even when it is ``0`` so that a
        # failed Provider can never become a plausible business zero.
        if blocked:
            return MetricSourceGateResult(
                status=SourceStatus.UNAVAILABLE,
                value=None,
                complete=False,
                required_domains=required,
                source_statuses=statuses,
                blocked_domains=blocked,
            )

        if any(
            snapshots[domain].status == SourceStatus.PARTIAL for domain in required
        ):
            return MetricSourceGateResult(
                status=SourceStatus.PARTIAL,
                value=proposed_value,
                complete=False,
                required_domains=required,
                source_statuses=statuses,
            )

        if any(
            snapshots[domain].status == SourceStatus.STALE for domain in required
        ):
            return MetricSourceGateResult(
                status=SourceStatus.STALE,
                value=proposed_value,
                complete=False,
                required_domains=required,
                source_statuses=statuses,
            )

        return MetricSourceGateResult(
            status=SourceStatus.OK,
            value=proposed_value,
            complete=True,
            required_domains=required,
            source_statuses=statuses,
        )
