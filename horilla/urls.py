"""Root URL configuration for the Yueke higher-education HR system."""

import notifications.urls
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.i18n import JavaScriptCatalog

from . import settings


def health_check(request):
    """Cheap liveness probe; does not touch dependencies."""
    return JsonResponse({"status": "ok"}, status=200)


def readiness_check(request):
    """Readiness probe for the signing database and configured Redis cache."""
    checks = {}
    try:
        connection.ensure_connection()
        checks["database"] = "ok"
        checks["database_vendor"] = connection.vendor
        if connection.vendor != "mysql":
            return JsonResponse(
                {
                    "status": "unavailable",
                    "database": "wrong vendor",
                    "database_vendor": connection.vendor,
                },
                status=503,
            )
    except Exception as exc:
        return JsonResponse(
            {"status": "unavailable", "database": str(exc)}, status=503
        )

    if getattr(settings, "REDIS_URL", None):
        try:
            cache.set("renshi_ready_probe", "1", timeout=5)
            if cache.get("renshi_ready_probe") != "1":
                raise RuntimeError("cache readback failed")
            checks["cache"] = "ok"
        except Exception as exc:
            return JsonResponse(
                {"status": "unavailable", "cache": str(exc), **checks}, status=503
            )

    return JsonResponse({"status": "ok", **checks}, status=200)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("base.urls")),
    path("", include("horilla_automations.urls")),
    path("", include("horilla_views.urls")),
    path("", include("horilla_audit.urls")),
    path("", include("horilla_tour.urls")),
    path("employee/", include("employee.urls")),
    path("horilla-widget/", include("horilla_widgets.urls")),
    re_path(
        "^inbox/notifications/", include(notifications.urls, namespace="notifications")
    ),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    # One explicit HR routing graph. AppConfig.ready() must not mutate this list.
    path("", include("horilla.hr_urls")),
    path("health/", health_check, name="health"),
    path("ready/", readiness_check, name="ready"),
]
