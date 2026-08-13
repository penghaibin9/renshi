"""Typed provider gateway for the HR17 SELF experience.

HR17 owns presentation and aggregation only.  Source business truth stays in
HR03-HR16.  Providers are isolated so one unavailable or failing source cannot
turn into a plausible empty value and cannot take down the whole SELF bootstrap.

The registry is intentionally extensible: source domains register adapters when
their real SELF read contract is available on the integration branch.  Missing
adapters remain explicitly UNAVAILABLE; HR17 never falls back to legacy tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

from django.utils import timezone

from hr_self.services.identity_service import SelfIdentityContext


class ProviderStatus:
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    ALL = frozenset({OK, PARTIAL, UNAVAILABLE, STALE, ERROR, NOT_APPLICABLE})


@dataclass(frozen=True)
class SelfProviderResult:
    status: str
    data: Any = None
    source_updated_at: Optional[datetime] = None
    error_code: str = ""
    error_message: str = ""
    provider_version: str = "1.0"
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ProviderStatus.ALL:
            raise ValueError(f"unsupported provider status: {self.status}")
        if self.status in {ProviderStatus.UNAVAILABLE, ProviderStatus.ERROR} and self.data is not None:
            raise ValueError("unavailable/error provider results must not carry business data")

    @classmethod
    def ok(cls, data, *, source_updated_at=None, provider_version="1.0", meta=None):
        return cls(
            status=ProviderStatus.OK,
            data=data,
            source_updated_at=source_updated_at,
            provider_version=provider_version,
            meta=meta or {},
        )

    @classmethod
    def unavailable(cls, code, message="", *, provider_version="1.0"):
        return cls(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_code=code,
            error_message=message,
            provider_version=provider_version,
        )

    @classmethod
    def error(cls, code, message="", *, provider_version="1.0"):
        return cls(
            status=ProviderStatus.ERROR,
            data=None,
            error_code=code,
            error_message=message,
            provider_version=provider_version,
        )


ProviderCallable = Callable[[SelfIdentityContext], SelfProviderResult]


class SelfProviderRegistry:
    REQUIRED_DOMAINS = tuple(f"HR{number:02d}" for number in range(3, 17))

    def __init__(self):
        self._providers: dict[str, ProviderCallable] = {}

    def register(self, domain: str, provider: ProviderCallable) -> None:
        domain = str(domain or "").strip().upper()
        if domain not in self.REQUIRED_DOMAINS:
            raise ValueError(f"unsupported HR17 source domain: {domain}")
        if not callable(provider):
            raise TypeError("provider must be callable")
        self._providers[domain] = provider

    def registered_domains(self) -> tuple[str, ...]:
        return tuple(domain for domain in self.REQUIRED_DOMAINS if domain in self._providers)

    def call(self, domain: str, context: SelfIdentityContext) -> SelfProviderResult:
        domain = str(domain or "").strip().upper()
        provider = self._providers.get(domain)
        if provider is None:
            return SelfProviderResult.unavailable(
                "SOURCE_PROVIDER_NOT_REGISTERED",
                f"{domain} SELF provider is not registered on this branch",
            )
        try:
            result = provider(context)
        except Exception as exc:
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_ERROR",
                f"{domain} provider failed: {type(exc).__name__}",
            )
        if not isinstance(result, SelfProviderResult):
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_CONTRACT_INVALID",
                f"{domain} provider returned an invalid envelope",
            )
        return result

    def collect(self, context: SelfIdentityContext) -> dict[str, SelfProviderResult]:
        return {domain: self.call(domain, context) for domain in self.REQUIRED_DOMAINS}


def hr03_self_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Real HR03 SELF adapter using the canonical effective-dated ProfileSelector."""

    from hr_staff.context import build_staff_context
    from hr_staff.selectors.profile import ProfileSelector

    hr03_context = build_staff_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope_type="SELF",
        scope_staff_ids=[context.staff_id],
        authority_mode="HR03_AUTHORITY",
    )
    data = ProfileSelector(hr03_context).bootstrap(context.staff_id)
    return SelfProviderResult.ok(
        data,
        source_updated_at=hr03_context.request_snapshot_at or timezone.now(),
        provider_version="hr03.profile-bootstrap.1",
        meta={"scope": "SELF", "authority": "HR03_AUTHORITY"},
    )


def default_self_provider_registry() -> SelfProviderRegistry:
    registry = SelfProviderRegistry()
    registry.register("HR03", hr03_self_provider)
    return registry
