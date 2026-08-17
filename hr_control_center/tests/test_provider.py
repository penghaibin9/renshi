"""
hr_control_center/tests/test_provider.py

Provider 合同（总册 33.5）：UNAVAILABLE/ERROR 绝不 fake zero。
"""

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    LEGACY_ONLY,
    HrProviderError,
    ProviderResult,
    provider_ok,
)
from hr_control_center.providers.legacy_employee import (
    LegacyEmployeeMetricProvider,
)
from hr_control_center.services.metric_registry import (
    OK,
    UNAVAILABLE,
)


class LegacyProviderContractTests(SimpleTestCase):
    def setUp(self):
        self.provider = LegacyEmployeeMetricProvider()
        self.ctx = HrRequestContext(
            tenant_id=1,
            school_timezone="Asia/Shanghai",
            as_of=None,
            authority_mode=LEGACY_ONLY,
        )

    def test_provider_result_status_validation(self):
        with self.assertRaises(ValueError):
            ProviderResult(status="BOGUS")

    def test_unavailable_is_not_zero(self):
        result = ProviderResult.unavailable(
            provider_key="x", metric_key="double_teacher_valid"
        )
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertIsNone(result.data)

    def test_double_teacher_is_unavailable_without_hr09(self):
        result = self.provider.get_metric("double_teacher_valid", self.ctx)
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertEqual(result.reason_code, "MODULE_NOT_AVAILABLE")

    def test_departure_ytd_unavailable_in_legacy(self):
        result = self.provider.get_metric("departure_ytd", self.ctx)
        self.assertEqual(result.status, UNAVAILABLE)

    def test_full_time_teacher_unavailable_without_dict(self):
        result = self.provider.get_metric("full_time_teacher", self.ctx)
        self.assertEqual(result.status, UNAVAILABLE)

    def test_unknown_metric_unavailable(self):
        result = self.provider.get_metric("not_a_metric", self.ctx)
        self.assertEqual(result.status, UNAVAILABLE)

    def test_provider_error_carries_tracking_fields(self):
        try:
            raise HrProviderError(
                "legacy_employee",
                "active_headcount",
                "HEADCOUNT_QUERY_FAILED",
                "boom",
                tenant_id=1,
                scope_fingerprint="SCHOOL:",
            )
        except HrProviderError as exc:
            self.assertEqual(exc.provider_key, "legacy_employee")
            self.assertEqual(exc.metric_key, "active_headcount")
            self.assertIn("provider=legacy_employee", str(exc))

    def test_provider_ok_helper(self):
        result = provider_ok({"value": 1}, source="x", data_basis="y")
        self.assertEqual(result.status, OK)
        self.assertEqual(result.data["value"], 1)
