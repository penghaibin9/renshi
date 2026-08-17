"""Tenant-safe inventory for retired Horilla report preference assets.

``report.ReportTemplate`` stores a user's saved pivot layout. It is not an HR18
metric, population, data-quality, snapshot, or submission Authority. Cutover
therefore inventories these rows for preference migration/archive instead of
pretending there is a one-to-one HR18 formal fact to reconcile against.
"""

from __future__ import annotations


class LegacyReportAssetInventoryService:
    """Inventory one tenant's legacy report templates without mutating them."""

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = int(tenant_id)

    def _legacy_rows(self, limit: int) -> tuple[int, list[dict]]:
        from report.models import ReportTemplate

        qs = (
            ReportTemplate.objects.entire()
            .filter(company_id_id=self.tenant_id)
            .order_by("-created_at", "-id")
        )
        total = qs.count()
        rows = list(
            qs.values(
                "id",
                "report_slug",
                "name",
                "config",
                "created_by_id",
                "created_at",
            )[:limit]
        )
        return total, rows

    def snapshot(self, *, limit: int = 200) -> dict:
        limit = max(1, min(int(limit), 500))
        total, rows = self._legacy_rows(limit)
        truncated = total > len(rows)
        items = [
            {
                "legacyReportTemplateId": str(row["id"]),
                "reportSlug": row["report_slug"],
                "name": row["name"],
                "createdById": row.get("created_by_id"),
                "createdAt": row.get("created_at"),
                "classification": "NON_AUTHORITY_PREFERENCE_ASSET",
                "legacyAuthority": False,
                "canonicalAuthorityMapping": None,
                "disposition": "MIGRATE_OR_ARCHIVE_USER_PREFERENCE",
                "config": row.get("config") or {},
            }
            for row in rows
        ]
        return {
            "status": "PARTIAL" if truncated else "COMPLETE",
            "authority": "HR18",
            "legacySource": "report.ReportTemplate",
            "legacyAuthority": False,
            "mappingPolicy": "NO_FORMAL_AUTHORITY_EQUIVALENT",
            "totalLegacyRows": total,
            "returnedRows": len(items),
            "truncated": truncated,
            "counts": {"nonAuthorityPreferenceAsset": len(items)},
            "items": items,
        }
