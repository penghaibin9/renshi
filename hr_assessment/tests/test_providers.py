"""S11 Provider 契约测试 — 真实 ORM 接入验证。"""

from django.test import TestCase
from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import (
    PersonProvider, OrganizationProvider, AgreementProvider,
    QualificationProvider, DevelopmentProvider, TimeSummaryProvider,
    AcademicProvider, ResearchProvider, EthicsFactProvider,
    PROVIDER_REGISTRY, get_provider,
)
import uuid


class ProviderContractTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.staff_id = uuid.uuid4()

    def test_person_provider_handles_empty_ids(self):
        p = PersonProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id, ids=[])
        result = p.fetch(ctx)
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_organization_provider_handles_empty_ids(self):
        p = OrganizationProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id, ids=[])
        result = p.fetch(ctx)
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_agreement_provider_handles_empty_ids(self):
        p = AgreementProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id, ids=[])
        result = p.fetch(ctx)
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_qualification_provider_handles_empty_ids(self):
        p = QualificationProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id, ids=[])
        result = p.fetch(ctx)
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_development_provider_unavailable(self):
        p = DevelopmentProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIsNone(result.data)
        self.assertGreater(len(result.error_message), 0)

    def test_time_summary_provider_handles_empty_ids(self):
        p = TimeSummaryProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id, ids=[])
        result = p.fetch(ctx)
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_academic_provider_unavailable(self):
        p = AcademicProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_research_provider_unavailable(self):
        p = ResearchProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_ethics_fact_provider_unavailable(self):
        p = EthicsFactProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_unavailable_is_not_zero_or_ok(self):
        self.assertNotEqual(ProviderStatus.UNAVAILABLE, ProviderStatus.OK)

    def test_provider_registry_all_entries(self):
        expected = {
            "person", "organization", "agreement", "qualification",
            "development", "time_summary", "academic", "research",
            "ethics_fact", "document", "archive", "notification",
        }
        self.assertEqual(set(PROVIDER_REGISTRY.keys()), expected)

    def test_get_provider_returns_correct_instance(self):
        p = get_provider("person")
        self.assertIsInstance(p, PersonProvider)
        self.assertIsNone(get_provider("nonexistent"))

    def test_provider_context_defaults(self):
        ctx = ProviderContext(tenant_id=self.tenant_id)
        self.assertIsNotNone(ctx.as_of)
        self.assertEqual(ctx.timeout_ms, 5000)

    def test_no_silent_fallback_legacy(self):
        p = DevelopmentProvider()
        ctx = ProviderContext(tenant_id=self.tenant_id)
        result = p.fetch(ctx)
        self.assertNotEqual(result.status, ProviderStatus.OK)
