"""Safe browser deep-link adapters for retired Horilla HR modules."""

from django.http import JsonResponse

from horilla.legacy_hr_api import HttpResponsePermanentRedirect308
from horilla.legacy_hr_cutover import (
    MUTATING_HTTP_METHODS,
    legacy_formal_write_frozen_response,
    record_legacy_write_attempt,
)


LEGACY_HR_UI_SUCCESSORS = {
    "payroll": "/hr/payroll/",
    "offboarding": "/hr/exit/",
    "report": "/hr/data/",
}


def legacy_hr_ui_redirect(request, domain, tail=""):
    """Move old browser bookmarks to canonical workspaces without reviving writes."""
    successor = LEGACY_HR_UI_SUCCESSORS.get(domain)
    if successor is None:
        return JsonResponse(
            {"error": {"code": "LEGACY_UI_DOMAIN_UNKNOWN"}},
            status=404,
        )

    method = str(request.method or "").upper()
    legacy_ref = f"{domain}/{tail}".rstrip("/")
    if method in MUTATING_HTTP_METHODS:
        record_legacy_write_attempt(
            request,
            surface="legacy-ui-deep-link",
            model_path=legacy_ref,
        )
        return legacy_formal_write_frozen_response(model_path=legacy_ref)

    if method not in {"GET", "HEAD"}:
        response = JsonResponse(
            {"error": {"code": "METHOD_NOT_ALLOWED"}},
            status=405,
        )
        response["Allow"] = "GET, HEAD"
        response["Cache-Control"] = "no-store"
        return response

    query = request.META.get("QUERY_STRING")
    target = f"{successor}?{query}" if query else successor
    response = HttpResponsePermanentRedirect308(target)
    response["Deprecation"] = "true"
    response["Sunset"] = "2026-12-31"
    response["Link"] = f'<{successor}>; rel="successor-version"'
    return response
