from django.test import SimpleTestCase
from django.urls import resolve

from horilla.urls import health_check, readiness_check


class InfrastructureProbeRouteTests(SimpleTestCase):
    def test_health_route_cannot_be_shadowed_by_legacy_urls(self):
        self.assertIs(resolve("/health/").func, health_check)

    def test_readiness_route_cannot_be_shadowed_by_legacy_urls(self):
        self.assertIs(resolve("/ready/").func, readiness_check)

