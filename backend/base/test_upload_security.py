import struct
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from base.upload_security import (
    MalwareScanError,
    MalwareScanMiddleware,
    ping_malware_scanner,
    scan_uploaded_file,
)


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = []
        self.closed = False

    def sendall(self, value):
        self.sent.append(value)

    def recv(self, size):
        response, self.response = self.response[:size], self.response[size:]
        return response

    def close(self):
        self.closed = True


@override_settings(
    MALWARE_SCAN_HOST="clamav",
    MALWARE_SCAN_PORT=3310,
    MALWARE_SCAN_TIMEOUT_SECONDS=2,
    MALWARE_SCAN_MAX_BYTES=1024 * 1024,
)
class ClamdProtocolTests(SimpleTestCase):
    @patch("base.upload_security.socket.create_connection")
    def test_clean_upload_uses_instream_and_restores_position(self, connect):
        sock = FakeSocket(b"stream: OK\0")
        connect.return_value = sock
        uploaded = SimpleUploadedFile("material.pdf", b"safe-content")
        uploaded.seek(4)

        scan_uploaded_file(uploaded)

        self.assertEqual(uploaded.tell(), 4)
        self.assertEqual(sock.sent[0], b"zINSTREAM\0")
        self.assertEqual(sock.sent[1], struct.pack(">I", len(b"safe-content")))
        self.assertEqual(sock.sent[2], b"safe-content")
        self.assertEqual(sock.sent[-1], struct.pack(">I", 0))
        self.assertTrue(sock.closed)

    @patch("base.upload_security.socket.create_connection")
    def test_infected_upload_fails_with_stable_code(self, connect):
        connect.return_value = FakeSocket(b"stream: Win.Test.EICAR FOUND\0")
        uploaded = SimpleUploadedFile("evidence.txt", b"test-signature")

        with self.assertRaises(MalwareScanError) as caught:
            scan_uploaded_file(uploaded)

        self.assertEqual(caught.exception.code, "malware_detected")
        self.assertEqual(uploaded.tell(), 0)

    @patch("base.upload_security.socket.create_connection", side_effect=OSError)
    def test_scanner_connection_failure_is_fail_closed(self, connect):
        with self.assertRaises(MalwareScanError) as caught:
            scan_uploaded_file(SimpleUploadedFile("case.pdf", b"content"))
        self.assertEqual(caught.exception.code, "scanner_unavailable")

    @patch("base.upload_security.socket.create_connection")
    def test_ping_requires_pong(self, connect):
        sock = FakeSocket(b"PONG\0")
        connect.return_value = sock

        ping_malware_scanner()

        self.assertEqual(sock.sent, [b"zPING\0"])


@override_settings(MALWARE_SCAN_REQUIRED=True)
class MalwareScanMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = MalwareScanMiddleware(lambda request: HttpResponse("view"))

    def test_scanner_runs_after_csrf_and_authentication_middleware(self):
        scanner = settings.MIDDLEWARE.index(
            "base.upload_security.MalwareScanMiddleware"
        )
        self.assertLess(
            settings.MIDDLEWARE.index("django.middleware.csrf.CsrfViewMiddleware"),
            scanner,
        )
        self.assertLess(
            settings.MIDDLEWARE.index(
                "django.contrib.auth.middleware.AuthenticationMiddleware"
            ),
            scanner,
        )

    def run_gate(self, request):
        rejection = self.middleware.process_view(request, lambda: None, (), {})
        return rejection or HttpResponse("view")

    @patch("base.upload_security.scan_uploaded_file")
    def test_clean_file_reaches_view(self, scan):
        request = self.factory.post(
            "/hr/onboarding/materials", {"file": SimpleUploadedFile("ok.pdf", b"ok")}
        )

        response = self.run_gate(request)

        self.assertEqual(response.status_code, 200)
        scan.assert_called_once()

    @patch("base.upload_security.scan_uploaded_file")
    def test_malware_is_rejected_before_view(self, scan):
        scan.side_effect = MalwareScanError("malware_detected", "found")
        request = self.factory.post(
            "/hr/exit/evidence", {"file": SimpleUploadedFile("bad.pdf", b"bad")}
        )

        response = self.run_gate(request)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b'"code": "malware_detected"', response.content)

    @patch("base.upload_security.scan_uploaded_file")
    def test_scanner_outage_returns_service_unavailable(self, scan):
        scan.side_effect = MalwareScanError("scanner_unavailable", "offline")
        request = self.factory.post(
            "/hr/staff/import", {"file": SimpleUploadedFile("staff.csv", b"a,b")}
        )

        response = self.run_gate(request)

        self.assertEqual(response.status_code, 503)
