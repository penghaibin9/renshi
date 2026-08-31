from django.contrib import admin

from hr_control_center.models import (
    HrAlertInstance,
    HrAuthorityCutover,
    HrDashboardPreference,
)


@admin.register(HrAlertInstance)
class HrAlertInstanceAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "title", "severity", "status", "due_at")
    list_filter = ("tenant_id", "severity", "status")
    search_fields = ("title", "summary", "dedupe_key")


@admin.register(HrAuthorityCutover)
class HrAuthorityCutoverAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "domain", "mode", "cutover_at", "reason")
    list_filter = ("tenant_id", "domain", "mode")


@admin.register(HrDashboardPreference)
class HrDashboardPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "user_id", "default_period")
