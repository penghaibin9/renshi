"""Safe browser deep-link adapters for retired Horilla HR modules."""

from django.http import HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers

from horilla.legacy_cutover_policy import (
    LEGACY_HR_UI_SUCCESSORS,
    apply_legacy_deprecation_headers,
)
from horilla.legacy_hr_api import HttpResponsePermanentRedirect308
from horilla.legacy_hr_cutover import (
    MUTATING_HTTP_METHODS,
    legacy_formal_write_frozen_response,
    record_legacy_write_attempt,
)


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
        response = legacy_formal_write_frozen_response(model_path=legacy_ref)
        return apply_legacy_deprecation_headers(response, successor=successor)

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
    # A retired workspace is a full document, not a settings-shell fragment.
    # Native redirects are followed inside XHR; hx-select would then select a
    # missing #settingsContainer and destroy the current page. HTMX consumes
    # HX-Redirect only on a non-3xx response. This changes navigation, NOT the
    # successor's authorization and NOT the frozen legacy write contract.
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
    else:
        response = HttpResponsePermanentRedirect308(target)
    response["Cache-Control"] = "no-store"
    patch_vary_headers(response, ("HX-Request",))
    return apply_legacy_deprecation_headers(response, successor=successor)
