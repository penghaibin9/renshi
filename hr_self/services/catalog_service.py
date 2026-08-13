"""HR17 self-service catalog reads/writes bound to SelfIdentityContext.

The caller never supplies ``staff_id`` for SELF operations. Ownership comes
only from the authenticated context produced by ``SelfIdentityService``.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from hr_self.models import SelfServiceCatalogItem, SelfServicePinnedService
from hr_self.services.identity_service import SelfIdentityContext, SelfIdentityError


class SelfCatalogError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SelfCatalogService:
    def __init__(self, context: SelfIdentityContext):
        if not context.tenant_id:
            raise SelfIdentityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.context = context

    def _catalog_item(self, service_code: str) -> SelfServiceCatalogItem:
        item = (
            SelfServiceCatalogItem.objects.filter(
                tenant_id=self.context.tenant_id,
                service_code=service_code,
                enabled=True,
            )
            .order_by("id")
            .first()
        )
        if item is None:
            # Do not disclose whether the code exists in another tenant or is disabled.
            raise SelfCatalogError(
                "SELF_SERVICE_NOT_AVAILABLE",
                "service is not available in the current SELF tenant",
            )
        return item

    def search(
        self,
        *,
        query: str = "",
        source_domain: str = "",
        limit: int = 24,
        offset: int = 0,
    ) -> dict:
        try:
            limit = int(limit)
            offset = int(offset)
        except (TypeError, ValueError) as exc:
            raise SelfCatalogError(
                "SELF_SERVICE_PAGINATION_INVALID",
                "limit and offset must be integers",
            ) from exc
        if limit < 1 or limit > 100 or offset < 0:
            raise SelfCatalogError(
                "SELF_SERVICE_PAGINATION_INVALID",
                "limit must be 1..100 and offset must be non-negative",
            )

        qs = SelfServiceCatalogItem.objects.filter(
            tenant_id=self.context.tenant_id,
            enabled=True,
        )
        query = str(query or "").strip()
        if query:
            qs = qs.filter(
                Q(service_code__icontains=query)
                | Q(name__icontains=query)
                | Q(action_key__icontains=query)
            )
        source_domain = str(source_domain or "").strip().upper()
        if source_domain:
            qs = qs.filter(source_domain=source_domain)

        qs = qs.order_by("sort_order", "name", "service_code")
        total = qs.count()
        pin_codes = set(
            SelfServicePinnedService.objects.filter(
                tenant_id=self.context.tenant_id,
                staff_id=self.context.staff_id,
            ).values_list("service_code", flat=True)
        )
        rows = list(
            qs[offset : offset + limit].values(
                "service_code",
                "name",
                "source_domain",
                "action_key",
                "route",
                "audience",
                "sort_order",
            )
        )
        for row in rows:
            row["pinned"] = row["service_code"] in pin_codes
        return {
            "items": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "query": query,
            "sourceDomain": source_domain or None,
        }

    @transaction.atomic
    def pin(self, *, service_code: str, sort_order: int = 100) -> SelfServicePinnedService:
        self._catalog_item(service_code)
        pin, _ = SelfServicePinnedService.objects.update_or_create(
            tenant_id=self.context.tenant_id,
            staff_id=self.context.staff_id,
            service_code=service_code,
            defaults={"sort_order": max(0, int(sort_order))},
        )
        return pin

    @transaction.atomic
    def unpin(self, *, service_code: str) -> int:
        # Ownership filter is mandatory even if service was disabled/deleted from
        # the current catalog after the user pinned it.
        deleted, _ = SelfServicePinnedService.objects.filter(
            tenant_id=self.context.tenant_id,
            staff_id=self.context.staff_id,
            service_code=service_code,
        ).delete()
        return deleted

    def list_pins(self):
        return SelfServicePinnedService.objects.filter(
            tenant_id=self.context.tenant_id,
            staff_id=self.context.staff_id,
        ).order_by("sort_order", "service_code")
