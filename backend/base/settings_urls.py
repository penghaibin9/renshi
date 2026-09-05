"""Canonical hardened routes for the legacy System Settings surface.

These patterns intentionally precede ``base.urls`` in the root resolver.  Their
public paths and names stay unchanged, while incoming requests are handled by
tenant-safe views in ``base.settings_center``.
"""

from django.urls import path

from base import settings_center


urlpatterns = [
    path(
        "settings/system-preferences-view/",
        settings_center.system_preferences_settings_view,
        name="system-preferences-view",
    ),
    path(
        "settings/pagination-settings-view/",
        settings_center.pagination_settings_view,
        name="pagination-settings-view",
    ),
    path(
        "settings/save-date/",
        settings_center.save_date_format,
        name="save_date_format",
    ),
    path(
        "settings/get-date-format/",
        settings_center.get_date_format,
        name="get-date-format",
    ),
    path(
        "settings/save-time/",
        settings_center.save_time_format,
        name="save_time_format",
    ),
    path(
        "settings/get-time-format/",
        settings_center.get_time_format,
        name="get-time-format",
    ),
    path(
        "settings/default-export-access/",
        settings_center.default_export_access_settings_view,
        name="default-export-access-settings",
    ),
    path(
        "enable-default-export-access/",
        settings_center.enable_default_export_access,
        name="enable-default-export-access",
    ),
    path(
        "settings/update-language-settings/",
        settings_center.update_language_settings,
        name="update-language-settings",
    ),
    path(
        "settings/company-view/",
        settings_center.company_view,
        name="company-view",
    ),
    path(
        "settings/company-update/<int:id>/",
        settings_center.company_update,
        name="company-update",
    ),
]
