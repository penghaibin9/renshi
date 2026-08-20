"""Fail-closed contracts for integrations that are not actually configured."""

from django.test import SimpleTestCase

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import DocumentProvider, NotificationProvider


class NoFakeSuccessProviderTests(SimpleTestCase):
    def setUp(self):
        self.ctx = ProviderContext(tenant_id=10001)

    def test_document_provider_does_not_report_ok_without_real_evidence_contract(self):
        result = DocumentProvider().fetch(self.ctx)

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIsNone(result.data)
        self.assertIn("未配置", result.error_message)
        self.assertEqual(result.source_version, "horilla_documents:unconfigured")

    def test_notification_provider_does_not_report_ok_without_delivery_receipt_contract(self):
        result = NotificationProvider().fetch(self.ctx)

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIsNone(result.data)
        self.assertIn("未配置", result.error_message)
        self.assertEqual(result.source_version, "notifications:unconfigured")
