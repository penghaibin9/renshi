"""Compatibility redirects for retired HR API roots."""

from django.http.response import HttpResponseRedirectBase

from horilla.legacy_cutover_policy import (
    LEGACY_API_SUCCESSOR_ROOT,
    apply_legacy_deprecation_headers,
)
from horilla.legacy_hr_cutover import (
    MUTATING_HTTP_METHODS,
    record_legacy_write_attempt,
)


class HttpResponsePermanentRedirect308(HttpResponseRedirectBase):
    status_code = 308
    status_code_preserve_request = 308


def legacy_hr_api_redirect(request, tail=""):
    """Preserve method/body while moving old clients to canonical HR APIs.

    This is an entry adapter only. A mutating request is measured as a legacy
    write attempt, but the retired application never regains formal write
    authority; the preserved request is transferred to the canonical API.
    """
    if str(request.method or "").upper() in MUTATING_HTTP_METHODS:
        record_legacy_write_attempt(
            request,
            surface="legacy-api-adapter",
            model_path=f"api/hr/v1/{tail}",
        )

    target = f"{LEGACY_API_SUCCESSOR_ROOT}{tail}"
    query = request.META.get("QUERY_STRING")
    if query:
        target = f"{target}?{query}"
    response = HttpResponsePermanentRedirect308(target)
    return apply_legacy_deprecation_headers(
        response,
        successor=target.split("?", 1)[0],
    )
