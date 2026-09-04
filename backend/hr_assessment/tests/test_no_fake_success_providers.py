"""Provider contracts: local evidence is real and receipt-backed."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import (
    ArchiveProvider,
    DocumentProvider,
    NotificationProvider,
)
from hr_assessment.service.evidence import ProviderCollectionOrchestrator
from horilla_documents.public import DocumentEvidenceRow


class NoFakeSuccessProviderTests(SimpleTestCase):
    def setUp(self):
        self.ctx = ProviderContext(tenant_id=10001)

    def test_document_provider_empty_query_is_complete(self):
        result = DocumentProvider().fetch(self.ctx)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])
        self.assertEqual(
            result.source_version,
            "horilla-documents-approved-evidence-v1",
        )

    @patch("horilla_documents.public.get_approved_document_evidence")
    def test_document_provider_returns_approved_metadata(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(SimpleNamespace(snapshot=lambda: {"staffId": str(staff_id)}),),
            missing_staff_ids=(),
        )
        result = DocumentProvider().fetch(
            ProviderContext(tenant_id=10001, ids=[staff_id])
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [{"staffId": str(staff_id)}])

    def test_document_snapshot_never_exposes_storage_path(self):
        snapshot = DocumentEvidenceRow(
            document_id=3,
            staff_id=uuid.uuid4(),
            title="年度业绩证明",
            request_title="年度考核材料",
            issue_date=None,
            expiry_date=None,
        ).snapshot()
        self.assertEqual(snapshot["documentRef"], "horilla-document:3")
        self.assertNotIn("path", snapshot)
        self.assertNotIn("url", snapshot)

    def test_document_capability_is_available(self):
        self.assertEqual(
            ProviderCollectionOrchestrator().capability_status()["document"],
            ProviderStatus.OK.value,
        )

    def test_notification_provider_empty_query_is_complete(self):
        result = NotificationProvider().fetch(self.ctx)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])
        self.assertEqual(result.source_version, "hr12-result-delivery-receipt-v1")

    def test_archive_provider_empty_query_is_complete(self):
        result = ArchiveProvider().fetch(self.ctx)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])
        self.assertEqual(result.source_version, "hr12-archive-v1")
