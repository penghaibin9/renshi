from unittest.mock import patch

from django.test import SimpleTestCase

from hr_control_center.api.views import _resolve_authority_mode
from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import HrProviderError, LEGACY_ONLY
from hr_control_center.providers.canonical_workforce import (
    CanonicalWorkforceMetricProvider,
)
from hr_control_center.providers.legacy_employee import LegacyEmployeeMetricProvider
from hr_control_center.services.overview_service import OverviewService


class CanonicalMetricRoutingTests(SimpleTestCase):
    def setUp(self):
        self.service = OverviewService()
        self.context = HrRequestContext(tenant_id=7, authority_mode=LEGACY_ONLY)

    def test_legacy_mode_uses_formal_domains_for_metrics_legacy_cannot_answer(self):
        for metric_key in (
            "full_time_teacher",
            "double_teacher_valid",
            "departure_ytd",
        ):
            self.assertIsInstance(
                self.service._resolve_provider(metric_key, LEGACY_ONLY),
                CanonicalWorkforceMetricProvider,
            )
        self.assertIsInstance(
            self.service._resolve_provider("active_headcount", LEGACY_ONLY),
            LegacyEmployeeMetricProvider,
        )

    def test_one_provider_failure_degrades_only_that_metric(self):
        class BrokenProvider:
            provider_key = "broken"

            def get_metric(self, metric_key, context):
                raise HrProviderError(
                    self.provider_key,
                    metric_key,
                    "BROKEN_SOURCE",
                    tenant_id=context.tenant_id,
                )

        self.service._resolve_provider = lambda metric_key, authority_mode: BrokenProvider()

        contract = self.service.get_metric("active_headcount", self.context)

        self.assertEqual(contract["status"], "ERROR")
        self.assertEqual(contract["reasonCode"], "BROKEN_SOURCE")
        self.assertIsNone(contract["value"])

    @patch("hr_staff.services.authority_mode_service.AuthorityModeService.get_mode")
    def test_request_context_uses_hr03_authority_mode(self, get_mode):
        get_mode.return_value = "HR03_AUTHORITY"
        self.assertEqual(_resolve_authority_mode(7), "AUTHORITY_ONLY")
        get_mode.return_value = "DUAL_READ_COMPARE"
        self.assertEqual(_resolve_authority_mode(7), "DUAL_READ_COMPARE")
