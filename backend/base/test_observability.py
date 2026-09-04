import json
import logging

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from base.observability import (
    JsonFormatter,
    RequestContextFilter,
    RequestIdMiddleware,
    redact_log_text,
)


class ObservabilityTests(SimpleTestCase):
    def test_request_id_is_preserved_when_safe(self):
        request = RequestFactory().get("/health/", HTTP_X_REQUEST_ID="uat-123")
        response = RequestIdMiddleware(lambda req: HttpResponse("ok"))(request)
        self.assertEqual(request.request_id, "uat-123")
        self.assertEqual(response["X-Request-ID"], "uat-123")

    def test_unsafe_request_id_is_replaced(self):
        request = RequestFactory().get("/health/", HTTP_X_REQUEST_ID="bad\nheader")
        response = RequestIdMiddleware(lambda req: HttpResponse("ok"))(request)
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_json_logs_have_context_and_redact_credentials(self):
        record = logging.LogRecord(
            "production.test",
            logging.INFO,
            __file__,
            1,
            "token=%s redis://user:redis-secret@redis:6379/0",
            ("plain-secret",),
            None,
        )
        RequestContextFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["logger"], "production.test")
        self.assertEqual(payload["request_id"], "-")
        self.assertNotIn("plain-secret", payload["message"])
        self.assertNotIn("redis-secret", payload["message"])

    def test_header_bearer_cookie_and_chinese_id_are_redacted(self):
        message = (
            "Authorization: Bearer eyJ.private.signature\n"
            "Cookie=sessionid=session-secret; csrftoken=csrf-secret\n"
            "fallback Bearer standalone-secret employee=110101199001011234"
        )
        redacted = redact_log_text(message)
        for secret in (
            "eyJ.private.signature",
            "session-secret",
            "csrf-secret",
            "standalone-secret",
            "110101199001011234",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("Authorization: [REDACTED]", redacted)
        self.assertIn("Cookie=[REDACTED]", redacted)
        self.assertIn("110101********1234", redacted)
