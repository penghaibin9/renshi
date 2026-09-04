from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from hr_onboarding.services.file_service import (
    material_storage_path,
    store_material_file,
)


class Hr05MaterialFileSecurityTests(SimpleTestCase):
    def test_storage_path_is_exact_and_normalizes_uuid_version(self):
        case_id = uuid.uuid4()
        material_id = uuid.uuid4()
        version_id = uuid.uuid4()

        path = material_storage_path(
            tenant_id=7,
            case_id=case_id,
            material_id=material_id,
            file_version_id=str(version_id),
            ext=".PDF",
        )

        self.assertEqual(
            path,
            f"hr05/7/{case_id}/{material_id}/{version_id.hex}.pdf",
        )
        self.assertNotIn(str(version_id), Path(path).name)

    def test_storage_path_rejects_invalid_ids_and_extensions(self):
        valid = uuid.uuid4()
        for version_id, ext in (("../secret", "pdf"), (valid, "html")):
            with self.subTest(version_id=version_id, ext=ext), self.assertRaises(ValueError):
                material_storage_path(
                    tenant_id=7,
                    case_id=valid,
                    material_id=valid,
                    file_version_id=version_id,
                    ext=ext,
                )

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    def test_production_upload_requires_completed_malware_scan(self):
        upload = SimpleUploadedFile(
            "proof.pdf", b"%PDF-1.7", content_type="application/pdf"
        )
        with self.assertRaisesMessage(ValueError, "MALWARE_SCAN_REQUIRED"):
            store_material_file(
                upload,
                tenant_id=7,
                case_id=uuid.uuid4(),
                material_id=uuid.uuid4(),
            )

    @override_settings(MALWARE_SCAN_REQUIRED=False)
    def test_stored_file_and_reconstructed_download_path_match(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            case_id = uuid.uuid4()
            material_id = uuid.uuid4()
            upload = SimpleUploadedFile(
                "proof.pdf", b"%PDF-1.7", content_type="application/pdf"
            )
            meta = store_material_file(
                upload,
                tenant_id=7,
                case_id=case_id,
                material_id=material_id,
            )
            path = material_storage_path(
                tenant_id=7,
                case_id=case_id,
                material_id=material_id,
                file_version_id=meta["file_version_id"],
                ext=meta["ext"],
            )
            self.assertTrue(Path(media_root, path).is_file())


class Hr05MaterialDownloadContractTests(SimpleTestCase):
    def test_download_uses_header_ticket_actor_binding_and_audit(self):
        root = Path(__file__).resolve().parent
        api_source = (root / "api" / "materials.py").read_text(encoding="utf-8")
        service_source = (root / "services" / "file_service.py").read_text(
            encoding="utf-8"
        )
        frontend_source = (
            root.parents[1]
            / "frontend"
            / "static"
            / "hr"
            / "js"
            / "pages"
            / "hr05-materials.js"
        ).read_text(encoding="utf-8")

        self.assertIn('request.headers.get("X-HR-Download-Ticket")', api_source)
        self.assertNotIn('request.GET.get("ticket")', api_source)
        self.assertIn("HrOnboardingAuditEvent.objects.create", api_source)
        self.assertIn("select_for_update", service_source)
        self.assertIn("actor_user_id", service_source)
        self.assertNotIn("django.core.cache", service_source)
        self.assertIn("X-HR-Access-Reason", frontend_source)
        self.assertIn("X-HR-Download-Ticket", frontend_source)
        self.assertIn("核验通过", frontend_source)
