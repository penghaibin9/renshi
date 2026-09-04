from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from hr_time.services.leave_evidence_file_service import (
    LeaveEvidenceFileError,
    delete_leave_evidence,
    open_leave_evidence,
    store_leave_evidence,
)


class LeaveEvidenceFileServiceTests(SimpleTestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()

    def tearDown(self):
        self.settings.disable()
        self.media.cleanup()

    def test_file_is_private_tenant_partitioned_and_hash_sealed(self):
        uploaded = SimpleUploadedFile(
            "门诊证明.pdf",
            b"%PDF-1.4 leave evidence",
            content_type="application/pdf",
        )
        metadata = store_leave_evidence(
            uploaded, tenant_id=8, leave_request_id=123
        )
        self.assertTrue(metadata["storage_key"].startswith("protected/hr11/8/123/"))
        self.assertNotIn("门诊证明", metadata["storage_key"])
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertEqual(metadata["file_size"], len(b"%PDF-1.4 leave evidence"))

        with open_leave_evidence(metadata["storage_key"], tenant_id=8) as stream:
            self.assertEqual(stream.read(), b"%PDF-1.4 leave evidence")
        with self.assertRaises(LeaveEvidenceFileError):
            open_leave_evidence(metadata["storage_key"], tenant_id=9)
        delete_leave_evidence(metadata["storage_key"])

    def test_extension_and_declared_mime_must_match(self):
        uploaded = SimpleUploadedFile(
            "证明.pdf", b"not a jpeg", content_type="image/jpeg"
        )
        with self.assertRaisesMessage(LeaveEvidenceFileError, "扩展名与内容类型不一致"):
            store_leave_evidence(uploaded, tenant_id=8, leave_request_id=123)
        self.assertEqual(list(Path(self.media.name).rglob("*.*")), [])

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    def test_production_upload_requires_completed_malware_scan(self):
        uploaded = SimpleUploadedFile(
            "证明.pdf", b"%PDF-1.4", content_type="application/pdf"
        )
        with self.assertRaises(LeaveEvidenceFileError) as caught:
            store_leave_evidence(uploaded, tenant_id=8, leave_request_id=123)
        self.assertEqual(caught.exception.code, "MALWARE_SCAN_REQUIRED")
        self.assertEqual(caught.exception.status, 503)


class LeaveEvidenceWiringContractTests(SimpleTestCase):
    def test_upload_download_and_editable_state_are_wired(self):
        base = Path(__file__).resolve().parents[1]
        api_source = (base / "api" / "workbench.py").read_text(encoding="utf-8")
        urls_source = (base / "api" / "urls.py").read_text(encoding="utf-8")
        template_source = (base / "templates" / "hr_time" / "workspace.html").read_text(
            encoding="utf-8"
        )
        frontend_source = (
            base.parents[1] / "frontend" / "static" / "hr" / "js" / "pages" / "hr11-actions.js"
        ).read_text(encoding="utf-8")

        self.assertIn('leave.status not in {"DRAFT", "RETURNED"}', api_source)
        self.assertIn("open_leave_evidence", api_source)
        self.assertIn("HrLeaveEvidenceAccessAudit.objects.create", api_source)
        self.assertIn("X-HR-Access-Reason", api_source)
        self.assertIn("leave-evidence/<int:evidence_id>/download", urls_source)
        self.assertIn('data-action="leave-evidence"', template_source)
        self.assertIn("data-evidence-download", template_source)
        self.assertIn("new FormData(form)", frontend_source)
        self.assertIn("X-HR-Access-Reason", frontend_source)
