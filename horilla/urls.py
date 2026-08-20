"""Root URL configuration for the Yueke higher-education HR system."""

import logging

import notifications.urls
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.i18n import JavaScriptCatalog

from . import settings

logger = logging.getLogger(__name__)


def health_check(request):
    """Cheap liveness probe; does not touch dependencies."""
    return JsonResponse({"status": "ok"}, status=200)


def readiness_check(request):
    """Readiness probe for the signing database and configured Redis cache.

    This endpoint is intentionally safe for an unauthenticated load balancer.
    Dependency exceptions are logged server-side and never reflected to the
    caller, because driver errors can contain hostnames, database names and
    other deployment topology details.
    """
    checks = {}
    try:
        connection.ensure_connection()
        checks["database"] = "ok"
        checks["database_vendor"] = connection.vendor
        if connection.vendor != "mysql":
            logger.error(
                "readiness rejected unexpected database vendor=%s",
                connection.vendor,
            )
            return JsonResponse(
                {"status": "unavailable", "database": "unavailable"},
                status=503,
            )
    except Exception:
        logger.exception("readiness database check failed")
        return JsonResponse(
            {"status": "unavailable", "database": "unavailable"}, status=503
        )

    if getattr(settings, "REDIS_URL", None):
        try:
            cache.set("renshi_ready_probe", "1", timeout=5)
            if cache.get("renshi_ready_probe") != "1":
                raise RuntimeError("cache readback failed")
            checks["cache"] = "ok"
        except Exception:
            logger.exception("readiness cache check failed")
            return JsonResponse(
                {"status": "unavailable", "cache": "unavailable", **checks},
                status=503,
            )

    return JsonResponse({"status": "ok", **checks}, status=200)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("platform_access.urls")),
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
