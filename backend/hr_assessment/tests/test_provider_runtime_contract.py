"""Provider runtime failure and batch-context contracts."""

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_assessment.providers.base import (
    BaseAssessmentProvider,
    ProviderContext,
    ProviderResult,
    ProviderStatus,
    circuit_breaker,
)


class _ErrorResultProvider(BaseAssessmentProvider):
    owner_domain = "test_error_result"
    retry_backoff = 0

    def __init__(self):
        self.calls = 0

    def _do_fetch(self, ctx):
        self.calls += 1
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message="runtime failure",
        )


class _RecordingProvider(BaseAssessmentProvider):
    owner_domain = "test_batch_context"
    retry_backoff = 0

    def __init__(self):
        self.contexts = []

    def _do_fetch(self, ctx):
        self.contexts.append(ctx)
        return ProviderResult(status=ProviderStatus.OK, data=list(ctx.ids))


class ProviderRuntimeContractTests(SimpleTestCase):
    def tearDown(self):
        circuit_breaker._failures.clear()
        circuit_breaker._last_failure_time.clear()

    @patch("hr_assessment.providers.base.time.sleep", return_value=None)
    def test_error_result_retries_and_records_failure(self, _sleep):
        provider = _ErrorResultProvider()
        ctx = ProviderContext(tenant_id=99101, ids=[1])

        result = provider.fetch(ctx)

        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertEqual(provider.calls, provider.max_retries + 1)
        self.assertEqual(
            circuit_breaker._failures["test_error_result:99101"],
            1,
        )

    def test_batch_preserves_security_and_trace_context(self):
        provider = _RecordingProvider()
        as_of = datetime(2026, 6, 30, tzinfo=timezone.utc)
        ctx = ProviderContext(
            tenant_id=99102,
            ids=[1, 2, 3],
            as_of=as_of,
            source_version="source-v7",
            max_stale_seconds=17,
            timeout_ms=1234,
            sensitivity="RESTRICTED_HR",
            request_id="req-123",
        )

        result = provider.fetch_batch(ctx, batch_size=2)

        self.assertEqual(len(result), 2)
        self.assertEqual([item.ids for item in provider.contexts], [[1, 2], [3]])
        for item in provider.contexts:
            self.assertEqual(item.as_of, as_of)
            self.assertEqual(item.source_version, "source-v7")
            self.assertEqual(item.max_stale_seconds, 17)
            self.assertEqual(item.timeout_ms, 1234)
            self.assertEqual(item.sensitivity, "RESTRICTED_HR")
            self.assertEqual(item.request_id, "req-123")

    def test_batch_size_must_be_positive(self):
        provider = _RecordingProvider()
        with self.assertRaises(ValueError):
            provider.fetch_batch(ProviderContext(tenant_id=99103, ids=[1]), batch_size=0)
