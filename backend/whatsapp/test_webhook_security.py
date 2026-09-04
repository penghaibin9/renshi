import hashlib
import hmac
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from whatsapp.security import valid_webhook_signature
from whatsapp.forms import WhatsappForm
from whatsapp.utils import (
    _allowed_meta_media_url,
    whatsapp_http_timeout,
    whatsapp_media_max_bytes,
)


class WhatsappWebhookSecurityTests(SimpleTestCase):
    def test_valid_signature_is_accepted(self):
        payload = b'{"object":"whatsapp_business_account"}'
        digest = hmac.new(b"app-secret", payload, hashlib.sha256).hexdigest()

        self.assertTrue(
            valid_webhook_signature(payload, f"sha256={digest}", ["app-secret"])
        )

    def test_missing_wrong_or_malformed_signature_is_rejected(self):
        payload = b"{}"
        self.assertFalse(valid_webhook_signature(payload, "", ["app-secret"]))
        self.assertFalse(
            valid_webhook_signature(payload, "sha1=abcd", ["app-secret"])
        )
        self.assertFalse(
            valid_webhook_signature(payload, "sha256=" + "0" * 64, ["app-secret"])
        )

    def test_webhook_uses_shared_cache_and_success_status(self):
        source = (Path(settings.BACKEND_DIR) / "whatsapp/views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("cache.add(dedupe_key", source)
        self.assertNotIn("processed_messages = set()", source)
        self.assertIn('HttpResponse("Message processed", status=200)', source)
        self.assertIn("_verified_webhook_credential", source)

    def test_credential_form_never_renders_stored_secrets(self):
        form = WhatsappForm()
        for field_name in ("meta_token", "meta_webhook_token", "meta_app_secret"):
            self.assertEqual(form.fields[field_name].widget.input_type, "password")
            self.assertFalse(form.fields[field_name].widget.render_value)

    @override_settings(WHATSAPP_HTTP_TIMEOUT_SECONDS=12)
    def test_http_timeout_is_bounded_and_configurable(self):
        self.assertEqual(whatsapp_http_timeout(), 12)
        with self.settings(WHATSAPP_HTTP_TIMEOUT_SECONDS=0):
            with self.assertRaises(ValueError):
                whatsapp_http_timeout()

        source = (Path(settings.BACKEND_DIR) / "whatsapp/utils.py").read_text(
            encoding="utf-8"
        )
        request_calls = source.count("requests.post(") + source.count("requests.get(")
        self.assertEqual(request_calls, source.count("timeout=whatsapp_http_timeout()"))

    def test_media_download_is_limited_to_https_meta_hosts(self):
        self.assertTrue(_allowed_meta_media_url("https://lookaside.fbsbx.com/media/1"))
        self.assertTrue(_allowed_meta_media_url("https://scontent.xx.fbcdn.net/media/1"))
        self.assertFalse(_allowed_meta_media_url("http://lookaside.fbsbx.com/media/1"))
        self.assertFalse(_allowed_meta_media_url("https://127.0.0.1/internal"))
        self.assertFalse(_allowed_meta_media_url("https://fbcdn.net.attacker.invalid/1"))
        self.assertFalse(_allowed_meta_media_url("https://user@lookaside.fbsbx.com/1"))

    @override_settings(WHATSAPP_MEDIA_MAX_BYTES=50 * 1024 * 1024)
    def test_media_size_limit_is_bounded(self):
        self.assertEqual(whatsapp_media_max_bytes(), 50 * 1024 * 1024)
        with self.settings(WHATSAPP_MEDIA_MAX_BYTES=50 * 1024 * 1024 + 1):
            with self.assertRaises(ValueError):
                whatsapp_media_max_bytes()

        source = (Path(settings.BACKEND_DIR) / "whatsapp/utils.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("stream=True", source)
        self.assertIn("response.iter_content", source)
