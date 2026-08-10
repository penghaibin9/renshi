from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_data.services.source_gate import (
    MetricSourceGate,
    MetricSourceGateError,
    ProviderSnapshot,
    SourceStatus,
)


class MetricSourceGateTests(SimpleTestCase):
    def _metric(self, *, tenant_id=77, domains=None):
        return SimpleNamespace(
            tenant_id=tenant_id,
            source_domains=domains if domains is not None else ["HR03"],
        )

    def test_unavailable_source_never_becomes_business_zero(self):
        result = MetricSourceGate(77).evaluate(
            metric_definition=self._metric(),
            proposed_value=0,
            provider_snapshots=[
                ProviderSnapshot(domain="HR03", status=SourceStatus.UNAVAILABLE)
            ],
        )

        self.assertEqual(result.status, SourceStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertFalse(result.complete)
        self.assertEqual(result.blocked_domains, ("HR03",))

    def test_missing_required_provider_is_explicitly_unavailable(self):
        result = MetricSourceGate(77).evaluate(
            metric_definition=self._metric(domains=["HR03", "HR14"]),
            proposed_value=12,
            provider_snapshots=[
                ProviderSnapshot(domain="HR03", status=SourceStatus.OK, value=12)
            ],
        )

        self.assertEqual(result.status, SourceStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertEqual(result.blocked_domains, ("HR14",))
        self.assertEqual(result.source_statuses["HR14"], SourceStatus.UNAVAILABLE.value)

    def test_partial_source_preserves_value_but_never_marks_complete(self):
        result = MetricSourceGate(77).evaluate(
            metric_definition=self._metric(),
            proposed_value=18,
            provider_snapshots=[
                ProviderSnapshot(domain="HR03", status=SourceStatus.PARTIAL, value=18)
            ],
        )

        self.assertEqual(result.status, SourceStatus.PARTIAL)
        self.assertEqual(result.value, 18)
        self.assertFalse(result.complete)

    def test_stale_source_preserves_value_with_stale_status(self):
        result = MetricSourceGate(77).evaluate(
            metric_definition=self._metric(),
            proposed_value=18,
            provider_snapshots=[
                ProviderSnapshot(domain="HR03", status=SourceStatus.STALE, value=18)
            ],
        )

        self.assertEqual(result.status, SourceStatus.STALE)
        self.assertEqual(result.value, 18)
        self.assertFalse(result.complete)

    def test_all_required_sources_ok_allows_complete_metric(self):
        result = MetricSourceGate(77).evaluate(
            metric_definition=self._metric(domains=["HR03", "HR14"]),
            proposed_value=21,
            provider_snapshots=[
                ProviderSnapshot(domain="HR03", status=SourceStatus.OK, value=20),
                ProviderSnapshot(domain="HR14", status=SourceStatus.OK, value=1),
            ],
        )

        self.assertEqual(result.status, SourceStatus.OK)
        self.assertEqual(result.value, 21)
        self.assertTrue(result.complete)
        self.assertEqual(result.blocked_domains, ())

    def test_cross_tenant_metric_definition_is_rejected(self):
        with self.assertRaises(MetricSourceGateError) as cm:
            MetricSourceGate(77).evaluate(
                metric_definition=self._metric(tenant_id=88),
                proposed_value=1,
                provider_snapshots=[
                    ProviderSnapshot(domain="HR03", status=SourceStatus.OK, value=1)
                ],
            )

        self.assertEqual(cm.exception.code, "METRIC_DEFINITION_CROSS_TENANT")
