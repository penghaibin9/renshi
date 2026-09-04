from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings
from pypdf import PdfReader

from base.pdf import PDFRenderError, render_html_to_pdf, safe_resource_path


class SafePDFRenderingTests(SimpleTestCase):
    def test_simple_html_renders_in_process(self):
        pdf = render_html_to_pdf("<html><body><h1>Payroll</h1></body></html>")

        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_simplified_chinese_text_is_preserved(self):
        pdf = render_html_to_pdf("<html><body>高校人事工资单</body></html>")

        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        self.assertIn("高校人事工资单", text)

    def test_remote_and_file_resources_are_rejected(self):
        for uri in (
            "https://example.com/logo.png",
            "file:///etc/passwd",
            "C:/Windows/win.ini",
        ):
            with self.subTest(uri=uri), self.assertRaises(PDFRenderError):
                safe_resource_path(uri)

    def test_active_inline_image_format_is_rejected(self):
        with self.assertRaises(PDFRenderError):
            safe_resource_path("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=")

    def test_media_resource_is_resolved_without_network_access(self):
        with TemporaryDirectory() as directory:
            media_root = Path(directory)
            logo = media_root / "tenant" / "logo.png"
            logo.parent.mkdir()
            logo.write_bytes(b"image")

            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                resolved = safe_resource_path(
                    "https://hr.example.edu/media/tenant/logo.png?signature=ignored"
                )

            self.assertEqual(Path(resolved), logo.resolve())

    def test_media_path_traversal_is_rejected(self):
        with TemporaryDirectory() as directory:
            with override_settings(MEDIA_ROOT=directory, MEDIA_URL="/media/"):
                with self.assertRaises(PDFRenderError):
                    safe_resource_path("/media/../secrets.txt")

    def test_oversized_html_is_rejected_before_rendering(self):
        with self.assertRaises(PDFRenderError):
            render_html_to_pdf("x" * (5 * 1024 * 1024 + 1))
