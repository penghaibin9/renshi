from unittest.mock import patch

from django.test import SimpleTestCase

from hr_self.services.bootstrap_service import SelfBootstrapService
from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    SelfProviderResult,
)


class Hr17BootstrapServiceTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.local = {
            "summary": {"availableServices": 3, "pinnedServices": 1, "sourceDomains": 2},
            "services": [{"service_code": "PROFILE", "name": "我的档案"}],
            "capabilities": {"selfIdentity": True, "serviceCatalog": True},
        }

    @patch("hr_self.services.bootstrap_service.dashboard_snapshot")
    def test_real_hr03_can_render_primary_status_while_other_domains_degrade(self, dashboard):
        dashboard.return_value = self.local
        registry = SelfProviderRegistry()
        registry.register(
            "HR03",
            lambda context: SelfProviderResult.ok(
                {
                    "identityHeader": {
                        "staffNo": "T001",
                        "legalName": "张老师",
                        "preferredName": "",
                        "employmentStatus": "ACTIVE",
                        "dataBasis": "HR03_AUTHORITY",
                    },
                    "currentFacts": {
                        "primaryAssignment": {
                            "orgName": "信息工程学院",
                            "positionName": "TEACHER",
                        },
                        "dateJoining": "2020-09-01",
                    },
                    "asOf": "2026-08-13",
                }
            ),
        )

        payload = SelfBootstrapService(self.context, registry=registry).build()

        self.assertEqual(payload["identity"]["staffNo"], "T001")
        self.assertEqual(payload["primaryStatus"]["assignment"]["orgName"], "信息工程学院")
        self.assertEqual(payload["providerHealth"]["HR03"]["status"], ProviderStatus.OK)
        self.assertEqual(payload["providerHealth"]["HR07"]["status"], ProviderStatus.UNAVAILABLE)
        self.assertIsNone(payload["providerData"]["HR07"])
        self.assertTrue(payload["degraded"])
        self.assertIn("HR07", payload["degradedDomains"])
        self.assertTrue(payload["capabilities"]["providerGateway"])
        self.assertTrue(payload["capabilities"]["hr03Provider"])
        self.assertFalse(payload["capabilities"]["hr03To16Providers"])

    @patch("hr_self.services.bootstrap_service.dashboard_snapshot")
    def test_provider_error_stays_in_health_and_bootstrap_still_builds(self, dashboard):
        dashboard.return_value = self.local
        registry = SelfProviderRegistry()
        registry.register("HR03", lambda context: SelfProviderResult.ok({}))
        registry.register(
            "HR11",
            lambda context: SelfProviderResult.error(
                "TIME_SOURCE_DOWN", "attendance source unavailable"
            ),
        )

        payload = SelfBootstrapService(self.context, registry=registry).build()

        self.assertEqual(payload["summary"]["availableServices"], 3)
        self.assertEqual(payload["providerHealth"]["HR11"]["status"], ProviderStatus.ERROR)
        self.assertEqual(payload["providerHealth"]["HR11"]["errorCode"], "TIME_SOURCE_DOWN")
        self.assertIsNone(payload["providerData"]["HR11"])
        self.assertTrue(payload["degraded"])

    @patch("hr_self.services.bootstrap_service.dashboard_snapshot")
    def test_partial_source_is_not_labelled_complete(self, dashboard):
        dashboard.return_value = self.local
        registry = SelfProviderRegistry()
        registry.register("HR03", lambda context: SelfProviderResult.ok({}))
        registry.register(
            "HR12",
            lambda context: SelfProviderResult(
                status=ProviderStatus.PARTIAL,
                data={"latestAssessment": None},
                error_code="ASSESSMENT_PARTIAL",
                error_message="one assessment source is incomplete",
            ),
        )

        payload = SelfBootstrapService(self.context, registry=registry).build()

        self.assertEqual(payload["providerHealth"]["HR12"]["status"], ProviderStatus.PARTIAL)
        self.assertEqual(payload["providerData"]["HR12"], {"latestAssessment": None})
        self.assertIn("HR12", payload["degradedDomains"])
        self.assertFalse(payload["capabilities"]["hr03To16Providers"])
