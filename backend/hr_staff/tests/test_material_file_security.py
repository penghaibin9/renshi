import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from hr_staff.services.material_file_service import (
    StaffMaterialFileError,
    open_staff_material,
    store_staff_material,
)

_ROOT = tempfile.mkdtemp(prefix="hr03-materials-")


@override_settings(MEDIA_ROOT=_ROOT, MALWARE_SCAN_REQUIRED=False)
class StaffMaterialFileSecurityTests(SimpleTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_ROOT, ignore_errors=True)

    def test_store_and_open_are_tenant_staff_partitioned(self):
        upload = SimpleUploadedFile(
            "学历证书.pdf", b"%PDF-1.4 staff material", content_type="application/pdf"
        )
        stored = store_staff_material(upload, tenant_id=8, staff_id="a-b-c")
        self.assertTrue(stored["storage_file_id"].startswith("protected/hr03/8/abc/"))
        stream = open_staff_material(
            stored["storage_file_id"], tenant_id=8, staff_id="a-b-c"
        )
        self.assertEqual(stream.read(), b"%PDF-1.4 staff material")
        stream.close()
        with self.assertRaises(StaffMaterialFileError):
            open_staff_material(stored["storage_file_id"], tenant_id=9, staff_id="a-b-c")

    def test_declared_mime_and_magic_must_match(self):
        with self.assertRaises(StaffMaterialFileError):
            store_staff_material(
                SimpleUploadedFile("fake.pdf", b"<html>", content_type="text/html"),
                tenant_id=8,
                staff_id="abc",
            )

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    def test_required_malware_marker_is_fail_closed(self):
        upload = SimpleUploadedFile(
            "proof.pdf", b"%PDF-1.4", content_type="application/pdf"
        )
        with self.assertRaisesMessage(StaffMaterialFileError, "材料尚未通过安全检查"):
            store_staff_material(upload, tenant_id=8, staff_id="abc")

    def test_path_traversal_and_legacy_unpartitioned_key_are_rejected(self):
        for key in ("../secret.pdf", "protected/legacy.pdf", "/protected/hr03/8/abc/a.pdf"):
            with self.subTest(key=key), self.assertRaises(StaffMaterialFileError):
                open_staff_material(key, tenant_id=8, staff_id="abc")
