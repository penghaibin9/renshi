"""Root URL configuration for the Yueke higher-education HR system."""

import logging

import notifications.urls
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.i18n import JavaScriptCatalog

from base.upload_security import MalwareScanError, ping_malware_scanner

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
        # ``ensure_connection()`` is a no-op when Django still holds a socket
        # object. Execute a real round-trip so a stopped/restarted MySQL server
        # cannot leave readiness falsely green on a stale pooled connection.
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("database probe returned an unexpected result")
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
        connection.close()
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

    if getattr(settings, "MALWARE_SCAN_REQUIRED", False):
        try:
            ping_malware_scanner()
            checks["malware_scanner"] = "ok"
        except MalwareScanError:
            logger.exception("readiness malware scanner check failed")
            return JsonResponse(
                {
                    "status": "unavailable",
                    "malware_scanner": "unavailable",
                    **checks,
                },
                status=503,
            )

    return JsonResponse({"status": "ok", **checks}, status=200)


urlpatterns = [
    # Infrastructure probes must be registered before compatibility URLConfs.
    # Several legacy apps contain broad fallback routes; placing probes later
    # can make a healthy process return a branded HTML/JSON 404 instead.
    path("health/", health_check, name="health"),
    path("ready/", readiness_check, name="ready"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("platform_access.urls")),
    # Canonical HR routes and legacy-UI retirement adapters must resolve before
    # old app URLConfs registered by compatibility AppConfig.ready() hooks.
    path("", include("horilla.hr_urls")),
    # Settings keeps legacy public paths/names but its tenant-safe handlers must
    # win URL resolution before the broad compatibility routes in base.urls.
    path("", include("base.settings_urls")),
    # Account authentication/notifications must not depend on an Employee row.
    path("", include("base.account_urls")),
    path("", include("base.urls")),
    path("", include("horilla_automations.urls")),
    path("", include("horilla_views.urls")),
    path("", include("horilla_audit.urls")),
    path("", include("horilla_tour.urls")),
    path("", include("horilla_ldap.urls")),
    path("employee/", include("employee.urls")),
    path("horilla-widget/", include("horilla_widgets.urls")),
    re_path(
        "^inbox/notifications/", include(notifications.urls, namespace="notifications")
    ),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
]
