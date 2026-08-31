"""Provider orchestrator must preserve historical and security context."""

from datetime import date
import uuid

from django.test import SimpleTestCase

from hr_assessment.providers.base import ProviderResult, ProviderStatus
from hr_assessment.service.evidence import ProviderCollectionOrchestrator


class _CaptureProvider:
    def __init__(self):
        self.context = None

    def fetch(self, ctx):
        self.context = ctx
        return ProviderResult(status=ProviderStatus.OK, data=[])


class ProviderOrchestratorContextTests(SimpleTestCase):
    def test_collect_one_preserves_as_of_and_policy_context(self):
        orchestrator = ProviderCollectionOrchestrator()
        capture = _CaptureProvider()
        orchestrator.providers = {"person": capture}
        staff_id = uuid.uuid4()

        result = orchestrator.collect_one(
            10001,
            staff_id,
            "person",
            as_of=date(2026, 6, 30),
            source_version="historical-v2",
            max_stale_seconds=19,
            timeout_ms=2345,
            sensitivity="RESTRICTED_HR",
            request_id="assessment-req-1",
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(capture.context.ids, [staff_id])
        self.assertEqual(capture.context.as_of, date(2026, 6, 30))
        self.assertEqual(capture.context.source_version, "historical-v2")
        self.assertEqual(capture.context.max_stale_seconds, 19)
        self.assertEqual(capture.context.timeout_ms, 2345)
        self.assertEqual(capture.context.sensitivity, "RESTRICTED_HR")
        self.assertEqual(capture.context.request_id, "assessment-req-1")

    def test_collect_all_reuses_same_historical_context_for_all_sources(self):
        orchestrator = ProviderCollectionOrchestrator()
        first = _CaptureProvider()
        second = _CaptureProvider()
        orchestrator.providers = {"person": first, "qualification": second}
        staff_ids = [uuid.uuid4(), uuid.uuid4()]

        results = orchestrator.collect_all(
            10002,
            staff_ids,
            as_of=date(2025, 12, 31),
            request_id="annual-2025",
        )

        self.assertEqual(set(results), {"person", "qualification"})
        for capture in (first, second):
            self.assertEqual(capture.context.ids, staff_ids)
            self.assertEqual(capture.context.as_of, date(2025, 12, 31))
            self.assertEqual(capture.context.request_id, "annual-2025")
