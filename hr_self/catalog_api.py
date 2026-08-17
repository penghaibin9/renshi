"""Canonical HTTP read boundary for HR17 SELF service discovery."""

from __future__ import annotations

from django.http import JsonResponse

from .api import HrSelfAccessError, _access_error, _method_not_allowed, resolve_self_context
from .services.catalog_service import SelfCatalogError, SelfCatalogService


def service_catalog(request):
    if request.method != "GET":
        return _method_not_allowed()
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return _access_error(exc)

    query = request.GET.get("q", "")
    source_domain = request.GET.get("sourceDomain", "")
    try:
        limit = int(request.GET.get("limit", 24))
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        response = JsonResponse(
            {"error": {"code": "SELF_SERVICE_PAGINATION_INVALID"}},
            status=400,
        )
        response["Cache-Control"] = "no-store"
        return response

    try:
        data = SelfCatalogService(context).search(
            query=query,
            source_domain=source_domain,
            limit=limit,
            offset=offset,
        )
    except SelfCatalogError as exc:
        response = JsonResponse(
            {"error": {"code": exc.code, "message": str(exc)}},
            status=400,
        )
        response["Cache-Control"] = "no-store"
        return response

    response = JsonResponse(
        {
            "data": data,
            "apiVersion": "1.0",
            "schemaVersion": "hr17.service-catalog.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
