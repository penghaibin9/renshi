"""Canonical API adapter for pre-PATCH-02 HR modules.

HR01/02/03/04/05/06/08/11 originally declared concrete handlers under
``/api/hr/v1``. During takeover we expose those *same callbacks* only under
``/api/v1/hr``. The old root is handled separately by a 308 compatibility
redirect, so new code cannot accidentally keep generating legacy URLs.
"""

from importlib import import_module

from django.urls import path
from django.urls.resolvers import URLPattern

LEGACY_API_MODULES = (
    "hr_control_center.api.urls",  # HR01
    "hr_structure.api.urls",  # HR02
    "hr_staff.api.urls",  # HR03
    "hr_recruitment.api.urls",  # HR04
    "hr_onboarding.api.urls",  # HR05
    "hr_changes.api.urls",  # HR06
    "hr_external.api.urls",  # HR08
    "hr_time.api.urls",  # HR11
)

LEGACY_PREFIX = "api/hr/v1/"
CANONICAL_PREFIX = "api/v1/hr/"


def _route_text(pattern):
    route = getattr(pattern.pattern, "_route", None)
    if route is None:
        route = str(pattern.pattern)
    return route


def _canonicalize(pattern, module_name):
    if not isinstance(pattern, URLPattern):
        raise RuntimeError(
            f"{module_name} contains nested URLResolver; migrate it explicitly before acceptance"
        )
    route = _route_text(pattern)
    if not route.startswith(LEGACY_PREFIX):
        raise RuntimeError(
            f"{module_name} contains non-canonicalizable route {route!r}; "
            f"expected prefix {LEGACY_PREFIX!r}"
        )
    canonical_route = CANONICAL_PREFIX + route[len(LEGACY_PREFIX) :]
    return path(
        canonical_route,
        pattern.callback,
        pattern.default_args or None,
        name=pattern.name,
    )


urlpatterns = []
for _module_name in LEGACY_API_MODULES:
    _module = import_module(_module_name)
    urlpatterns.extend(
        _canonicalize(_pattern, _module_name) for _pattern in _module.urlpatterns
    )
