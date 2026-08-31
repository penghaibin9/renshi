"""S11 Provider contract tests."""

import uuid

from django.test import TestCase

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import (
    PROVIDER_REGISTRY,
    AcademicProvider,
    AgreementProvider,
    DevelopmentProvider,
    EthicsFactProvider,
    OrganizationProvider,
    PersonProvider,
    QualificationProvider,
    ResearchProvider,
    TimeSummaryProvider,
    get_provider,
)


class ProviderContractTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.staff_id = uuid.uuid4()

    def test_person_provider_handles_empty_ids(self):
        result = PersonProvider().fetch(ProviderContext(tenant_id=self.tenant_id, ids=[]))
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_organization_provider_handles_empty_ids(self):
        result = OrganizationProvider().fetch(
            ProviderContext(tenant_id=self.tenant_id, ids=[])
        )
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_agreement_provider_handles_empty_ids(self):
        result = AgreementProvider().fetch(
            ProviderContext(tenant_id=self.tenant_id, ids=[])
        )
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_qualification_provider_handles_empty_ids(self):
        result = QualificationProvider().fetch(
            ProviderContext(tenant_id=self.tenant_id, ids=[])
        )
        self.assertIn(result.status, (ProviderStatus.OK, ProviderStatus.PARTIAL))

    def test_development_provider_handles_empty_ids_without_fake_unavailable(self):
        result = DevelopmentProvider().fetch(
            ProviderContext(tenant_id=self.tenant_id, ids=[])
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])
        self.assertEqual(result.source_version, "hr10-development-fact-v1")

    def test_time_summary_provider_handles_empty_ids(self):
        result = TimeSummaryProvider().fetch(
            ProviderContext(tenant_id=self.tenant_id, ids=[])
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])
        self.assertEqual(result.source_version, "hr11-time-close-v1")

    def test_academic_provider_unavailable(self):
        result = AcademicProvider().fetch(ProviderContext(tenant_id=self.tenant_id))
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_research_provider_unavailable(self):
        result = ResearchProvider().fetch(ProviderContext(tenant_id=self.tenant_id))
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_ethics_fact_provider_unavailable(self):
        result = EthicsFactProvider().fetch(ProviderContext(tenant_id=self.tenant_id))
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_unavailable_is_not_zero_or_ok(self):
        self.assertNotEqual(ProviderStatus.UNAVAILABLE, ProviderStatus.OK)

    def test_provider_registry_all_entries(self):
        expected = {
            "person",
            "organization",
            "agreement",
            "qualification",
            "development",
            "time_summary",
            "academic",
            "research",
            "ethics_fact",
            "document",
            "archive",
            "notification",
        }
        self.assertEqual(set(PROVIDER_REGISTRY.keys()), expected)

    def test_get_provider_returns_correct_instance(self):
        provider = get_provider("person")
        self.assertIsInstance(provider, PersonProvider)
        self.assertIsNone(get_provider("nonexistent"))

    def test_provider_context_defaults(self):
        ctx = ProviderContext(tenant_id=self.tenant_id)
        self.assertIsNotNone(ctx.as_of)
        self.assertEqual(ctx.timeout_ms, 5000)
