from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from hr_recruitment.services.plan_service import PlanService


class DefaultCapacityProviderContractTests(SimpleTestCase):
    @patch("hr_recruitment.integrations.hr02.Hr02CapacityProvider")
    def test_plan_approval_uses_hr02_authority_provider_by_default(self, provider_class):
        provider = Mock()
        provider.query_capacity.return_value = SimpleNamespace(
            status="OK", available_count=3
        )
        provider_class.return_value = provider
        line = SimpleNamespace(
            request_id=SimpleNamespace(organization_id=9),
            post_catalog_id=10,
            position_id=11,
            position_pool_id=None,
            requested_headcount=2,
        )

        available = PlanService()._available_headcount(line, tenant_id=7)

        self.assertEqual(available, 2)
        provider_class.assert_called_once_with(tenant_id=7)
        provider.query_capacity.assert_called_once_with(
            tenant_id=7,
            organization_id=9,
            post_catalog_id=10,
            position_id=11,
            position_pool_id=None,
        )
