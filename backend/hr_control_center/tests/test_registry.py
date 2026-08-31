"""
hr_control_center/tests/test_registry.py

MetricDefinition / freshness 合同（总册 33.1）。
"""

from django.test import SimpleTestCase

from hr_control_center.services.metric_registry import (
    METRIC_DEFINITIONS,
    get_registry,
)


class MetricRegistryTests(SimpleTestCase):
    def test_core_metrics_registered(self):
        registry = get_registry()
        for key in (
            "active_headcount",
            "full_time_teacher",
            "double_teacher_valid",
            "new_join_ytd",
            "departure_ytd",
            "open_risk_count",
        ):
            self.assertIsNotNone(registry.get(key), key)

    def test_every_metric_has_freshness_contract(self):
        for key, definition in METRIC_DEFINITIONS.items():
            with self.subTest(key=key):
                self.assertGreaterEqual(definition.cache_ttl_seconds, 0)
                self.assertGreaterEqual(definition.max_stale_seconds, definition.cache_ttl_seconds)
                self.assertGreaterEqual(definition.hard_expire_seconds, definition.max_stale_seconds)
                self.assertTrue(definition.definition_version)

    def test_definition_version_present(self):
        self.assertEqual(METRIC_DEFINITIONS["active_headcount"].definition_version, "1.0")

    def test_double_teacher_owner_domain_is_hr09(self):
        self.assertEqual(
            METRIC_DEFINITIONS["double_teacher_valid"].owner_domain, "hr09"
        )

    def test_open_risk_no_stale_on_error(self):
        # 当前 CRITICAL 风险数量不允许失败时继续展示旧值
        self.assertFalse(METRIC_DEFINITIONS["open_risk_count"].serve_stale_on_error)
