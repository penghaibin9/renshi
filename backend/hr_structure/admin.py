from django.contrib import admin

from hr_structure import models


@admin.register(models.HrOrganization)
class HrOrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "stable_code", "org_dimension", "identity_status")
    list_filter = ("tenant_id", "org_dimension", "identity_status")
    search_fields = ("stable_code",)


@admin.register(models.HrOrganizationVersion)
class HrOrganizationVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "name", "org_type", "status", "validity_from", "validity_to")
    list_filter = ("tenant_id", "org_type", "status")
    search_fields = ("name",)


@admin.register(models.HrOrganizationRelation)
class HrOrganizationRelationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "source_org_id", "relation_type", "target_org_id", "validity_from")
    list_filter = ("tenant_id", "relation_type", "status")


@admin.register(models.HrStaffingPlan)
class HrStaffingPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "code", "name", "plan_year", "status")
    list_filter = ("tenant_id", "status")


@admin.register(models.HrPostCatalog)
class HrPostCatalogAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "stable_code")


@admin.register(models.HrPostCatalogVersion)
class HrPostCatalogVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "name", "category", "subcategory", "status", "version_no")
    list_filter = ("tenant_id", "category", "status")


@admin.register(models.HrPosition)
class HrPositionAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "position_code", "organization_id", "lifecycle_status")
    list_filter = ("tenant_id", "lifecycle_status")


@admin.register(models.HrPositionReservation)
class HrPositionReservationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "reservation_no", "status", "source_business_id")
    list_filter = ("tenant_id", "status")


@admin.register(models.HrStructureChangeCase)
class HrStructureChangeCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "case_no", "change_type", "title", "status")
    list_filter = ("tenant_id", "change_type", "status")


@admin.register(models.HrLegacyObjectLink)
class HrLegacyObjectLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "domain_entity_type", "legacy_model", "legacy_pk", "link_status")
    list_filter = ("tenant_id", "legacy_model", "link_status")
