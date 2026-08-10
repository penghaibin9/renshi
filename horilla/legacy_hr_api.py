"""Compatibility redirects for retired HR API roots."""

from django.http.response import HttpResponseRedirectBase


class HttpResponsePermanentRedirect308(HttpResponseRedirectBase):
    status_code = 308
    status_code_preserve_request = 308


def legacy_hr_api_redirect(request, tail=""):
    """Preserve method/body while moving old clients to /api/v1/hr/... ."""
    target = f"/api/v1/hr/{tail}"
    query = request.META.get("QUERY_STRING")
    if query:
        target = f"{target}?{query}"
    response = HttpResponsePermanentRedirect308(target)
    response["Deprecation"] = "true"
    response["Sunset"] = "2026-12-31"
    response["Link"] = f'<{target.split("?", 1)[0]}>; rel="successor-version"'
    return response
