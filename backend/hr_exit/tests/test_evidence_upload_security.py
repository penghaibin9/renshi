from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from hr_exit.evidence_upload import (
    EvidenceUploadError,
    _validated_storage_name,
    save_evidence,
)


class Hr16EvidenceUploadSecurityTests(SimpleTestCase):
    def test_cross_tenant_and_traversal_storage_refs_are_rejected(self):
        invalid = (
            "storage://protected/hr16/8/handover/proof.pdf",
            "storage://protected/hr16/7/handover/../proof.pdf",
            "storage://protected/hr16/7/archive-package/folder/proof.pdf",
        )
        for reference in invalid:
            with self.subTest(reference=reference), self.assertRaises(EvidenceUploadError):
                _validated_storage_name(
                    reference,
                    tenant_id=7,
                    allowed_categories={"handover", "archive-package"},
                )

    @override_settings(MALWARE_SCAN_REQUIRED=False)
    def test_mime_mismatch_is_rejected(self):
        upload = SimpleUploadedFile(
            "proof.pdf", b"not-a-pdf", content_type="text/html"
        )
        with self.assertRaises(EvidenceUploadError) as caught:
            save_evidence(upload, tenant_id=7, category="handover")
        self.assertEqual(caught.exception.code, "EVIDENCE_FILE_TYPE_MISMATCH")

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    def test_production_upload_requires_completed_malware_scan(self):
        upload = SimpleUploadedFile(
            "proof.pdf", b"%PDF-1.7", content_type="application/pdf"
        )
        with self.assertRaises(EvidenceUploadError) as caught:
            save_evidence(upload, tenant_id=7, category="handover")
        self.assertEqual(caught.exception.code, "MALWARE_SCAN_REQUIRED")
        self.assertEqual(caught.exception.status, 503)
