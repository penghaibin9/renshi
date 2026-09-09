"""One durable receipt per school; business facts stay in HR02's existing tables."""

from django.db import models


class HrSchoolStructureInitialization(models.Model):
    tenant_id = models.BigIntegerField(unique=True)
    request_hash = models.CharField(max_length=64)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    root_version = models.ForeignKey(
        "HrOrganizationVersion", on_delete=models.PROTECT, related_name="initial_school_receipts"
    )
    department_version = models.ForeignKey(
        "HrOrganizationVersion", on_delete=models.PROTECT, related_name="initial_department_receipts"
    )
    catalog_version = models.ForeignKey("HrPostCatalogVersion", on_delete=models.PROTECT)
    position = models.ForeignKey("HrPosition", on_delete=models.PROTECT)

    class Meta:
        # No independent CRUD surface: this is the transaction receipt, not a
        # second place to edit school, organization, catalog or position data.
        default_permissions = ()
