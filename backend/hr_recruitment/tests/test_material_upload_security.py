from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings

LEGACY_MEDIA_ROUTE_AVAILABLE = apps.is_installed("base")
if LEGACY_MEDIA_ROUTE_AVAILABLE:
    from base.views import protected_media
from hr_recruitment.api.application import download_material
from hr_recruitment.constants import SensitiveLevel
from hr_recruitment.material_storage import (
    MaterialStorageError,
    delete_application_material,
    open_application_material,
    store_application_material,
)


@override_settings(
    MALWARE_SCAN_REQUIRED=False,
    HR04_APPLICATION_MATERIAL_MAX_BYTES=1024,
)
class MaterialStorageTests(SimpleTestCase):
    @patch("hr_recruitment.material_storage.default_storage")
    def test_server_generates_tenant_partition_and_digest(self, storage):
        storage.save.side_effect = lambda key, upload: key
        upload = SimpleUploadedFile("教师资格证.pdf", b"trusted-content", "application/pdf")

        result = store_application_material(upload, tenant_id=7, application_id="app-1")

        self.assertTrue(result["file_path"].startswith("protected/hr04/7/app-1/"))
        self.assertEqual(result["file_size_bytes"], len(b"trusted-content"))
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(result["mime_type"], "application/pdf")

    def test_rejects_extension_content_type_mismatch(self):
        upload = SimpleUploadedFile("resume.pdf", b"x", "image/png")
        with self.assertRaises(MaterialStorageError) as caught:
            store_application_material(upload, tenant_id=7, application_id="app-1")
        self.assertEqual(caught.exception.code, "MATERIAL_FILE_TYPE_MISMATCH")

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    def test_production_requires_middleware_scan_marker(self):
        upload = SimpleUploadedFile("resume.pdf", b"x", "application/pdf")
        with self.assertRaises(MaterialStorageError) as caught:
            store_application_material(upload, tenant_id=7, application_id="app-1")
        self.assertEqual(caught.exception.code, "MALWARE_SCAN_REQUIRED")

    @patch("hr_recruitment.material_storage.default_storage")
    def test_delete_refuses_cross_partition_key(self, storage):
        with self.assertRaises(MaterialStorageError):
            delete_application_material(
                "protected/hr04/8/app-1/file.pdf",
                tenant_id=7,
                application_id="app-1",
            )
        storage.delete.assert_not_called()

    @patch("hr_recruitment.material_storage.default_storage")
    def test_open_requires_exact_partition_and_existing_object(self, storage):
        storage.exists.return_value = True
        expected_stream = object()
        storage.open.return_value = expected_stream

        stream = open_application_material(
            "protected/hr04/7/app-1/file.pdf",
            tenant_id=7,
            application_id="app-1",
        )

        self.assertIs(stream, expected_stream)
        storage.open.assert_called_once_with(
            "protected/hr04/7/app-1/file.pdf", "rb"
        )

    @patch("hr_recruitment.material_storage.default_storage")
    def test_open_rejects_traversal_even_inside_partition_prefix(self, storage):
        with self.assertRaises(MaterialStorageError):
            open_application_material(
                "protected/hr04/7/app-1/../other/file.pdf",
                tenant_id=7,
                application_id="app-1",
            )
        storage.open.assert_not_called()


class MaterialUploadEndpointContractTests(SimpleTestCase):
    def test_endpoint_never_accepts_client_storage_metadata(self):
        source = (
            Path(__file__).resolve().parents[1] / "api" / "application.py"
        ).read_text(encoding="utf-8")
        section = source[source.index("def add_material"):]
        self.assertIn('request.content_type != "multipart/form-data"', section)
        self.assertIn('request.FILES.get("file")', section)
        self.assertIn("store_application_material(", section)
        self.assertNotIn('body.get("file_path"', section)
        self.assertNotIn('body.get("sha256"', section)
        self.assertNotIn('body.get("mime_type"', section)

    def test_service_enforces_partition_digest_size_and_retention(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "application_service.py"
        ).read_text(encoding="utf-8")
        section = source[source.index("def add_material"):]
        self.assertIn('expected_prefix = f"protected/hr04/', section)
        self.assertIn('len(sha256) != 64', section)
        self.assertIn('int(file_size_bytes or 0) <= 0', section)
        self.assertIn("retention_until=app.candidate_id.retention_until", section)

    def test_download_is_tenant_scoped_permissioned_audited_and_never_uses_media_url(self):
        app_root = Path(__file__).resolve().parents[1]
        source = (app_root / "api" / "application.py").read_text(encoding="utf-8")
        section = source[source.index("def download_material"):]
        for marker in (
            "tenant_id=ctx.tenant_id",
            "application_id_id=application_id",
            'has_perm("hr04.application.view")',
            'has_perm("hr04.application.sensitive_view")',
            'request.headers.get("X-HR-Access-Reason"',
            "open_application_material(",
            "log_sensitive_access(",
            'response["Cache-Control"] = "private, no-store, max-age=0"',
        ):
            self.assertIn(marker, section)
        self.assertNotIn("default_storage.url", section)

        base_views = (app_root.parent / "base" / "views.py").read_text(
            encoding="utf-8"
        )
        protected_media = base_views[base_views.index("def protected_media"):]
        self.assertIn('"protected/",', protected_media)
        self.assertIn('"hr_contracts_private/",', protected_media)
        self.assertIn('"external-materials/",', protected_media)
        self.assertIn('"hr05/",', protected_media)
        self.assertIn('"hr10/imports/",', protected_media)
        self.assertIn('"hr-export/",', protected_media)
        self.assertIn("normalized_path.startswith(private_media_prefixes)", protected_media)

    def test_tenant_isolation_security_gate_is_not_permanently_skipped(self):
        security_test = (
            Path(__file__).resolve().parent / "test_security_s11.py"
        ).read_text(encoding="utf-8")
        class_section = security_test[
            security_test.index("class TenantIsolationSecurityTests") :
        ]
        self.assertNotIn("@unittest.skip", security_test)
        self.assertIn("id=TENANT_A", class_section)
        self.assertIn("id=TENANT_B", class_section)


class MaterialDownloadEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.application_id = uuid4()
        self.material_id = uuid4()

    @staticmethod
    def _user(*permissions):
        permission_set = set(permissions)
        return SimpleNamespace(
            id=19,
            is_superuser=False,
            is_authenticated=True,
            has_perm=lambda code: code in permission_set,
        )

    def _material(self, level):
        return SimpleNamespace(
            id=self.material_id,
            file_path=(
                f"protected/hr04/7/{self.application_id}/{self.material_id}.pdf"
            ),
            file_name="教师资格证.pdf",
            mime_type="application/pdf",
            sensitive_level=level,
            application_id=SimpleNamespace(candidate_id_id=uuid4()),
        )

    @patch("hr_recruitment.models.HrApplicationMaterial")
    @patch("hr_recruitment.api.application.make_hr04_context")
    def test_sensitive_download_requires_sensitive_permission(
        self, make_context, material_model
    ):
        make_context.return_value = SimpleNamespace(tenant_id=7)
        material_model.objects.select_related.return_value.filter.return_value.first.return_value = self._material(
            SensitiveLevel.SENSITIVE
        )
        request = self.factory.get("/download")
        request.user = self._user("hr04.application.view")

        response = download_material(request, self.application_id, self.material_id)

        self.assertEqual(response.status_code, 403)

    @patch("hr_recruitment.models.HrApplicationMaterial")
    @patch("hr_recruitment.api.application.make_hr04_context")
    def test_high_sensitive_download_requires_reason(
        self, make_context, material_model
    ):
        make_context.return_value = SimpleNamespace(tenant_id=7)
        material_model.objects.select_related.return_value.filter.return_value.first.return_value = self._material(
            SensitiveLevel.HIGH_SENSITIVE
        )
        request = self.factory.get("/download")
        request.user = self._user(
            "hr04.application.view", "hr04.application.sensitive_view"
        )

        response = download_material(request, self.application_id, self.material_id)

        self.assertEqual(response.status_code, 422)

    @patch("hr_recruitment.services.audit_service.log_sensitive_access")
    @patch("hr_recruitment.material_storage.open_application_material")
    @patch("hr_recruitment.models.HrApplicationMaterial")
    @patch("hr_recruitment.api.application.make_hr04_context")
    def test_authorized_download_is_audited_and_not_cached(
        self, make_context, material_model, open_material, audit
    ):
        make_context.return_value = SimpleNamespace(tenant_id=7)
        material = self._material(SensitiveLevel.HIGH_SENSITIVE)
        material_model.objects.select_related.return_value.filter.return_value.first.return_value = material
        open_material.return_value = BytesIO(b"pdf")
        request = self.factory.get(
            "/download", HTTP_X_HR_ACCESS_REASON="资格复核"
        )
        request.user = self._user(
            "hr04.application.view", "hr04.application.sensitive_view"
        )
        request.request_id = "req-1"

        response = download_material(request, self.application_id, self.material_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        open_material.assert_called_once_with(
            material.file_path,
            tenant_id=7,
            application_id=self.application_id,
        )
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["reason"], "资格复核")
        response.close()

    @skipUnless(LEGACY_MEDIA_ROUTE_AVAILABLE, "requires installed legacy media route")
    def test_generic_media_route_never_serves_canonical_protected_files(self):
        request = self.factory.get("/media/protected/hr04/7/example/file.pdf")
        request.user = self._user("hr04.application.view")
        with self.assertRaises(Http404):
            protected_media(request, "protected/hr04/7/example/file.pdf")

    @skipUnless(LEGACY_MEDIA_ROUTE_AVAILABLE, "requires installed legacy media route")
    def test_generic_media_route_never_serves_other_private_namespaces(self):
        for private_path in (
            "hr_contracts_private/7/example.pdf",
            "external-materials/example.pdf",
            "hr05/7/example.pdf",
            "hr10/imports/7/source/example.xlsx",
            "hr-export/7/example.csv",
        ):
            with self.subTest(private_path=private_path):
                request = self.factory.get(f"/media/{private_path}")
                request.user = self._user("hr04.application.view")
                with self.assertRaises(Http404):
                    protected_media(request, private_path)
