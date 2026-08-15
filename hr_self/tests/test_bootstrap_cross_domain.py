from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_self.services.bootstrap_service import SelfBootstrapService
from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    SelfProviderResult,
)


class Hr17BootstrapCrossDomainGateTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )

    @patch("hr_self.services.bootstrap_service.dashboard_snapshot")
    def test_one_source_failure_does_not_erase_other_authority_data(self, dashboard_snapshot):
        dashboard_snapshot.return_value = {
            "summary": {"serviceCount": 3},
            "services": [],
            "capabilities": {"catalog": True},
        }
        registry = SelfProviderRegistry()
        source_time = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)

        registry.register(
            "HR03",
            lambda _context: SelfProviderResult.ok(
                {
                    "identityHeader": {
                        "staffNo": "T0001",
                        "legalName": "测试教师",
                        "employmentStatus": "ACTIVE",
                    },
                    "currentFacts": {"primaryAssignment": {"orgName": "信息工程学院"}},
                    "asOf": "2026-08-15T01:02:03+00:00",
                },
                source_updated_at=source_time,
                provider_version="hr03-test",
            ),
        )

        def broken_hr07(_context):
            raise RuntimeError("source unavailable")

        registry.register("HR07", broken_hr07)
        registry.register(
            "HR09",
            lambda _context: SelfProviderResult.ok(
                {"credentials": [{"name": "教师资格证", "status": "ACTIVE"}]},
                source_updated_at=source_time,
                provider_version="hr09-test",
                meta={"scope": "SELF", "authority": "HR09_QUALIFICATION_AUTHORITY"},
            ),
        )

        payload = SelfBootstrapService(self.context, registry=registry).build()

        self.assertEqual(payload["identity"]["staffId"], self.context.staff_id)
        self.assertEqual(payload["providerHealth"]["HR07"]["status"], ProviderStatus.ERROR)
        self.assertEqual(payload["providerHealth"]["HR07"]["errorCode"], "SOURCE_PROVIDER_ERROR")
        self.assertIsNone(payload["providerData"]["HR07"])

        self.assertEqual(payload["providerHealth"]["HR09"]["status"], ProviderStatus.OK)
        self.assertEqual(payload["providerData"]["HR09"]["credentials"][0]["status"], "ACTIVE")

        self.assertEqual(payload["providerHealth"]["HR11"]["status"], ProviderStatus.UNAVAILABLE)
        self.assertEqual(
            payload["providerHealth"]["HR11"]["errorCode"],
            "SOURCE_PROVIDER_NOT_REGISTERED",
        )
        self.assertIsNone(payload["providerData"]["HR11"])
        self.assertTrue(payload["degraded"])
        self.assertIn("HR07", payload["degradedDomains"])
        self.assertIn("HR11", payload["degradedDomains"])
        self.assertFalse(payload["capabilities"]["hr03To16Providers"])

    @patch("hr_self.services.bootstrap_service.dashboard_snapshot")
    def test_all_registered_domains_can_be_healthy_without_recomputing_source_truth(self, dashboard_snapshot):
        dashboard_snapshot.return_value = {"summary": {}, "services": [], "capabilities": {}}
        registry = SelfProviderRegistry()
        for domain in registry.REQUIRED_DOMAINS:
            registry.register(
                domain,
                lambda _context, source_domain=domain: SelfProviderResult.ok(
                    {"sourceDomain": source_domain},
                    provider_version=f"{source_domain.lower()}-test",
                    meta={"scope": "SELF", "authority": f"{source_domain}_AUTHORITY"},
                ),
            )

        payload = SelfBootstrapService(self.context, registry=registry).build()

        self.assertFalse(payload["degraded"])
        self.assertEqual(payload["degradedDomains"], [])
        self.assertTrue(payload["capabilities"]["hr03To16Providers"])
        self.assertEqual(
            set(payload["registeredProviderDomains"]),
            set(registry.REQUIRED_DOMAINS),
        )
        for domain in registry.REQUIRED_DOMAINS:
            self.assertEqual(payload["providerHealth"][domain]["status"], ProviderStatus.OK)
            self.assertEqual(payload["providerData"][domain]["sourceDomain"], domain)
