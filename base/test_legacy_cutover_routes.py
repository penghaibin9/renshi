"""Production cutover contract for retired legacy HR write surfaces."""

from django.test import RequestFactory, SimpleTestCase
from django.urls import URLResolver, get_resolver, resolve

from horilla.legacy_hr_api import (
    HttpResponsePermanentRedirect308,
    legacy_hr_api_redirect,
)


RETIRED_FORMAL_AUTHORITY_MODULES = ("payroll", "offboarding", "report")


def _module_is_retired_legacy(module_name):
    return any(
        module_name == root or module_name.startswith(f"{root}.")
        for root in RETIRED_FORMAL_AUTHORITY_MODULES
    )


def _walk_urlpatterns(patterns, prefix=""):
    for entry in patterns:
        route = f"{prefix}{entry.pattern}"
        if isinstance(entry, URLResolver):
            urlconf_name = entry.urlconf_name
            if isinstance(urlconf_name, str):
                yield route, urlconf_name, "urlconf"
            elif hasattr(urlconf_name, "__name__"):
                yield route, urlconf_name.__name__, "urlconf"
            yield from _walk_urlpatterns(entry.url_patterns, route)
            continue

        callback = entry.callback
        module_name = getattr(callback, "__module__", "")
        yield route, module_name, "callback"


class LegacyFormalWriteCutoverContractTests(SimpleTestCase):
    """Legacy payroll/offboarding/report must be unreachable as formal writers."""

    def test_retired_legacy_authority_urlconfs_and_callbacks_are_unreachable(self):
        offenders = [
            (route, module_name, kind)
            for route, module_name, kind in _walk_urlpatterns(get_resolver().url_patterns)
            if _module_is_retired_legacy(module_name)
        ]
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Retired legacy Authority route became reachable again; formal writes "
                f"must remain zero after cutover: {offenders}"
            ),
        )

    def test_legacy_api_mutating_verbs_are_adapter_only_308_redirects(self):
        factory = RequestFactory()
        resolver_path = "/api/hr/v1/payroll/periods/42/"
        request_path = f"{resolver_path}?tenant=7"
        expected_location = "/api/v1/hr/payroll/periods/42/?tenant=7"

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                match = resolve(resolver_path)
                self.assertIs(match.func, legacy_hr_api_redirect)

                request = factory.generic(
                    method,
                    request_path,
                    data=b'{"formal":"write-attempt"}',
                    content_type="application/json",
                )
                response = match.func(request, **match.kwargs)

                self.assertIsInstance(response, HttpResponsePermanentRedirect308)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response["Location"], expected_location)
                self.assertEqual(response["Deprecation"], "true")
                self.assertIn('rel="successor-version"', response["Link"])

    def test_legacy_adapter_uses_request_preserving_redirect_status(self):
        self.assertEqual(HttpResponsePermanentRedirect308.status_code, 308)
        self.assertEqual(HttpResponsePermanentRedirect308.status_code_preserve_request, 308)
