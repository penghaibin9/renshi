from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr10_development.api.imports import (
    _error_workbook_payload,
    _validated_error_workbook_path,
    download_error_workbook,
)


class ImportFileSecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _view():
        return download_error_workbook.__wrapped__.__wrapped__

    def test_internal_storage_path_is_never_returned_to_browser(self):
        job = SimpleNamespace(
            id=42,
            tenant_id=7,
            error_workbook_path="hr10/imports/7/errors/job-42.xlsx",
        )
        payload = _error_workbook_payload(job)
        self.assertTrue(payload["hasErrorWorkbook"])
        self.assertEqual(
            payload["errorWorkbookDownloadUrl"],
            "/api/v1/hr/development/imports/42/errors/download",
        )
        self.assertNotIn("errorWorkbookPath", payload)
        self.assertEqual(
            _validated_error_workbook_path(job), job.error_workbook_path
        )
        job.error_workbook_path = "hr10/imports/8/errors/job-42.xlsx"
        with self.assertRaises(ValueError):
            _validated_error_workbook_path(job)

    def test_download_requires_recorded_business_purpose(self):
        request = self.factory.get("/errors/download")
        request.tenant_id = 7
        request.user = SimpleNamespace(id=31)
        response = self._view()(request, 42)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"DOWNLOAD_PURPOSE_REQUIRED", response.content)

    @patch("hr10_development.api.imports.HrDevelopmentAuditEvent.objects.create")
    @patch("hr10_development.api.imports.default_storage.open")
    @patch("hr10_development.api.imports.default_storage.exists", return_value=True)
    @patch("hr10_development.api.imports.HrDevelopmentImportJob.objects.filter")
    def test_authorized_download_is_tenant_scoped_audited_and_not_cached(
        self, filter_jobs, _exists, open_file, create_audit
    ):
        job = SimpleNamespace(
            id=42,
            tenant_id=7,
            error_workbook_path="hr10/imports/7/errors/job-42.xlsx",
        )
        filter_jobs.return_value.first.return_value = job
        open_file.return_value = io.BytesIO(b"xlsx")
        request = self.factory.get(
            "/errors/download",
            HTTP_X_HR_ACCESS_REASON="修正教师发展导入错误",
            HTTP_X_REQUEST_ID="req-42",
        )
        request.tenant_id = 7
        request.user = SimpleNamespace(id=31)

        response = self._view()(request, 42)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        filter_jobs.assert_called_once_with(id=42, tenant_id=7)
        create_audit.assert_called_once()
        self.assertEqual(create_audit.call_args.kwargs["actor_id_id"], 31)
        self.assertEqual(
            create_audit.call_args.kwargs["reason"], "修正教师发展导入错误"
        )
        response.close()

    def test_contract_blocks_all_related_private_media_namespaces(self):
        source = (
            Path(__file__).resolve().parents[2] / "base" / "views.py"
        ).read_text(encoding="utf-8")
        for prefix in ('"hr05/",', '"hr10/imports/",', '"hr-export/",'):
            self.assertIn(prefix, source)
