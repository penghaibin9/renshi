"""Single-call HR17 SELF bootstrap aggregation.

The bootstrap keeps HR17 as an Experience Authority: it combines the local
service catalog/pins with typed read-only source providers.  It never converts
source failures to empty business values and never owns source workflow state.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from hr_self.selectors import dashboard_snapshot
from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    default_self_provider_registry,
)


class SelfBootstrapService:
    def __init__(
        self,
        context: SelfIdentityContext,
        *,
        registry: Optional[SelfProviderRegistry] = None,
    ):
        if not context or not context.tenant_id or not context.staff_id:
            raise ValueError("resolved SELF identity is required")
        self.context = context
        self.registry = registry or default_self_provider_registry()

    @staticmethod
    def _iso(value):
        return value.isoformat() if value is not None else None

    def build(self) -> dict:
        local = dashboard_snapshot(self.context)
        results = self.registry.collect(self.context)

        provider_health = {}
        provider_data = {}
        for domain, result in results.items():
            provider_health[domain] = {
                "status": result.status,
                "sourceUpdatedAt": self._iso(result.source_updated_at),
                "errorCode": result.error_code or None,
                "errorMessage": result.error_message or None,
                "providerVersion": result.provider_version,
            }
            if result.status in {
                ProviderStatus.OK,
                ProviderStatus.PARTIAL,
                ProviderStatus.STALE,
                ProviderStatus.NOT_APPLICABLE,
            }:
                provider_data[domain] = result.data
            else:
                provider_data[domain] = None

        hr03 = results["HR03"]
        hr03_data = hr03.data if hr03.status in {
            ProviderStatus.OK,
            ProviderStatus.PARTIAL,
            ProviderStatus.STALE,
        } and isinstance(hr03.data, dict) else {}
        identity_header = hr03_data.get("identityHeader") or {}
        current_facts = hr03_data.get("currentFacts") or {}

        degraded_domains = [
            domain
            for domain, result in results.items()
            if result.status in {
                ProviderStatus.PARTIAL,
                ProviderStatus.UNAVAILABLE,
                ProviderStatus.STALE,
                ProviderStatus.ERROR,
            }
        ]
        registered = set(self.registry.registered_domains())
        all_required_registered = len(registered) == len(self.registry.REQUIRED_DOMAINS)

        capabilities = dict(local.get("capabilities") or {})
        capabilities.update(
            {
                "providerGateway": True,
                "bootstrap": True,
                "hr03Provider": hr03.status in {
                    ProviderStatus.OK,
                    ProviderStatus.PARTIAL,
                    ProviderStatus.STALE,
                },
                # This remains false until every required source has a real
                # registered provider; partial integration is never labelled complete.
                "hr03To16Providers": all_required_registered,
            }
        )

        return {
            "identity": {
                "staffNo": identity_header.get("staffNo"),
                "legalName": identity_header.get("legalName"),
                "preferredName": identity_header.get("preferredName"),
                "employmentStatus": identity_header.get("employmentStatus"),
                "dataBasis": identity_header.get("dataBasis"),
            },
            "primaryStatus": {
                "assignment": current_facts.get("primaryAssignment"),
                "dateJoining": current_facts.get("dateJoining"),
                "asOf": hr03_data.get("asOf"),
                "status": hr03.status,
            },
            "summary": local.get("summary") or {},
            "services": local.get("services") or [],
            "capabilities": capabilities,
            "providerHealth": provider_health,
            "providerData": provider_data,
            "degraded": bool(degraded_domains),
            "degradedDomains": degraded_domains,
            "registeredProviderDomains": list(self.registry.registered_domains()),
        }
