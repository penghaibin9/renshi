from django.urls import path

from platform_access import views

urlpatterns = [
    path(
        "api/platform/v1/tenant-elevation/activate/",
        views.activate_tenant_elevation,
        name="platform-tenant-elevation-activate",
    ),
    path(
        "api/platform/v1/tenant-elevation/revoke/",
        views.revoke_current_tenant_elevation,
        name="platform-tenant-elevation-revoke",
    ),
    path(
        "api/platform/v1/tenant-elevation/status/",
        views.tenant_elevation_status,
        name="platform-tenant-elevation-status",
    ),
]
