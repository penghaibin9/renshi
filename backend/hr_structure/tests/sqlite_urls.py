"""Canonical HR02 browser and API routes for isolated tests."""

from django.urls import include, path, re_path

from horilla.legacy_hr_api import legacy_hr_api_redirect
from hr_structure.api.urls import urlpatterns as legacy_api_patterns


def _canonical_pattern(pattern):
    route = pattern.pattern._route
    legacy_prefix = "api/hr/v1/"
    if not route.startswith(legacy_prefix):
        raise RuntimeError(f"unexpected HR02 legacy API route: {route}")
    return path(
        "api/v1/hr/" + route[len(legacy_prefix) :],
        pattern.callback,
        pattern.default_args or None,
        name=pattern.name,
    )


urlpatterns = [
    path("hr/structure/", include("hr_structure.urls")),
    *[_canonical_pattern(pattern) for pattern in legacy_api_patterns],
    re_path(
        r"^api/hr/v1/(?P<tail>.*)$",
        legacy_hr_api_redirect,
        name="legacy-hr-api",
    ),
]
