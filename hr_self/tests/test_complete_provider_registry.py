from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_self.services.authority_providers import (
    hr08_self_provider,
    hr11_self_provider,
)
from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    default_self_provider_registry,
)


class Hr17CompleteProviderRegistryTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )

    def test_default_registry_has_real_adapter_for_every_hr03_hr16_domain(self):
        registry = default_self_provider_registry()
        self.assertEqual(
            registry.registered_domains(),
            SelfProviderRegistry.REQUIRED_DOMAINS,
        )

    def test_hr11_missing_identity_mapping_is_unavailable_not_empty_data(self):
        context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id=self.context.staff_id,
            person_id=self.context.person_id,
            legacy_employee_id=None,
        )

        result = hr11_self_provider(context)

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
        self.assertIsNone(result.data)

    @patch("hr_external.models.HrExternalEngagement")
    def test_hr08_is_tenant_and_person_scoped_and_excludes_internal_profile(self, model):
        row = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000801",
            engagement_no="EXT-2026-001",
            purpose="兼职授课",
            host_organization_id=22,
            start_at=None,
            end_at=None,
            review_at=None,
            agreement_status="ACTIVE",
            status="ACTIVE",
            current_risk_level="INFO",
            updated_at=None,
        )
        model.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [row]

        result = hr08_self_provider(self.context)

        model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data["externalEngagements"][0]["status"], "ACTIVE")
        self.assertNotIn("externalProfileId", result.data["externalEngagements"][0])
        self.assertEqual(result.meta["scope"], "SELF")
