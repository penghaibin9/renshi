"""Read models for HR17 SELF experience.

Every selector is bound to SelfIdentityContext. Callers never provide staff_id.
"""
from .models import SelfServiceCatalogItem, SelfServicePinnedService


def dashboard_snapshot(context) -> dict:
    if not context or not context.tenant_id or not context.staff_id:
        raise ValueError("resolved SELF identity is required")
    catalog = SelfServiceCatalogItem.objects.filter(
        tenant_id=context.tenant_id,
        enabled=True,
    ).order_by("sort_order", "name")
    pins = SelfServicePinnedService.objects.filter(
        tenant_id=context.tenant_id,
        staff_id=context.staff_id,
    ).order_by("sort_order", "service_code")
    pin_codes = set(pins.values_list("service_code", flat=True))
    services = list(catalog[:24].values(
        "service_code", "name", "source_domain", "action_key", "route", "audience", "sort_order"
    ))
    for item in services:
        item["pinned"] = item["service_code"] in pin_codes
    return {
        "summary": {
            "availableServices": catalog.count(),
            "pinnedServices": pins.count(),
            "sourceDomains": catalog.values("source_domain").distinct().count(),
        },
        "services": services,
        "capabilities": {
            "selfIdentity": True,
            "serviceCatalog": True,
            "serviceSearch": True,
            "pinnedServices": True,
            "home": True,
            "providerGateway": True,
            "providerRegistration": True,
            "hr03To16Providers": True,
            "todos": True,
            "progress": True,
            "files": False,
            "payslipContractAggregation": False,
            "mobileHighFrequency": True,
            "idorGuard": True,
        },
    }
