import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from base.middleware import TwoFactorAuthMiddleware
from base.views import set_otp, verify_otp


@override_settings(
    EMAIL_HOST="smtp.university.edu",
    EMAIL_PORT=587,
    EMAIL_HOST_USER="smtp-user",
    EMAIL_HOST_PASSWORD="smtp-secret",
    EMAIL_USE_TLS=True,
    EMAIL_USE_SSL=False,
    EMAIL_TIMEOUT=10,
    DEFAULT_FROM_EMAIL="noreply@university.edu",
)
class DeploymentEmailBoundaryTests(SimpleTestCase):
    @patch("base.backends.EmailBackend")
    def test_security_email_uses_only_deployment_smtp_settings(self, backend_class):
        from base.backends import send_deployment_email

        backend = backend_class.return_value
        backend.send_messages.return_value = 1

        result = send_deployment_email(
            subject="Security code",
            body="123456",
            to=["user@university.edu"],
        )

        self.assertEqual(result, 1)
        backend_class.assert_called_once_with(
            host="smtp.university.edu",
            port=587,
            username="smtp-user",
            password="smtp-secret",
            use_tls=True,
            use_ssl=False,
            timeout=10,
            fail_silently=False,
        )
        message = backend.send_messages.call_args.args[0][0]
        self.assertEqual(message.from_email, "noreply@university.edu")
        self.assertEqual(message.to, ["user@university.edu"])


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "mfa-security-tests",
        }
    },
    SECRET_KEY="test-mfa-secret-key-that-is-long-enough",
    TWO_FACTORS_AUTHENTICATION=True,
    MFA_OTP_TTL_SECONDS=300,
    MFA_OTP_MAX_ATTEMPTS=3,
    MFA_OTP_RESEND_COOLDOWN_SECONDS=60,
)
class EmailOtpSecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.post("/two-factor/", {"otp": "123456"})
        SessionMiddleware(lambda request: HttpResponse("ok")).process_request(
            self.request
        )
        self.request.user = SimpleNamespace(pk=42, is_authenticated=True)
        self.request._messages = FallbackStorage(self.request)

    @patch("base.views.generate_otp", return_value="123456")
    def test_otp_is_hashed_bound_to_user_and_never_stored_in_plaintext(self, _):
        otp = set_otp(self.request)

        self.assertEqual(otp, "123456")
        self.assertNotIn("otp_code", self.request.session)
        self.assertNotEqual(self.request.session["otp_code_hash"], otp)
        self.assertEqual(self.request.session["otp_code_user_id"], "42")
        self.assertEqual(verify_otp(self.request, otp), "verified")

    @patch("base.views.generate_otp", return_value="123456")
    def test_otp_cannot_be_replayed_for_another_authenticated_user(self, _):
        set_otp(self.request)
        self.request.user = SimpleNamespace(pk=43, is_authenticated=True)

        self.assertEqual(verify_otp(self.request, "123456"), "missing")
        self.assertNotIn("otp_code_hash", self.request.session)

    @patch("base.views.render", side_effect=lambda _request, _template, **kwargs: HttpResponse(status=kwargs.get("status", 200)))
    @patch("base.views.send_deployment_email", return_value=1)
    @patch("base.views.generate_otp", return_value="123456")
    def test_delivery_sets_challenge_and_shared_resend_cooldown(
        self, _generate, _send, _render
    ):
        from base import views

        self.request.user.employee_get = SimpleNamespace(
            is_active=True, get_mail=lambda: "user@university.edu"
        )
        cooldown_key = "mfa_otp_cooldown:42"
        cache.delete(cooldown_key)
        self.addCleanup(cache.delete, cooldown_key)
        raw_send_otp = inspect.unwrap(views.send_otp)

        response = raw_send_otp(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("otp_code_hash", self.request.session)
        self.assertTrue(cache.get(cooldown_key))

        response = raw_send_otp(self.request)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(_send.call_count, 1)

    @patch("base.views.render", side_effect=lambda _request, _template, **kwargs: HttpResponse(status=kwargs.get("status", 200)))
    @patch(
        "base.views.send_deployment_email",
        side_effect=OSError("smtp unavailable"),
    )
    @patch("base.views.generate_otp", return_value="123456")
    def test_delivery_failure_destroys_challenge_and_releases_cooldown(
        self, _generate, _send, _render
    ):
        from base import views

        self.request.user.employee_get = SimpleNamespace(
            is_active=True, get_mail=lambda: "user@university.edu"
        )
        cooldown_key = "mfa_otp_cooldown:42"
        cache.delete(cooldown_key)
        self.addCleanup(cache.delete, cooldown_key)

        response = inspect.unwrap(views.send_otp)(self.request)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("otp_code_hash", self.request.session)
        self.assertIsNone(cache.get(cooldown_key))

    @patch("base.views.generate_otp", return_value="123456")
    def test_invalid_attempts_lock_and_destroy_pending_challenge(self, _):
        set_otp(self.request)

        self.assertEqual(verify_otp(self.request, "111111"), "invalid")
        self.assertEqual(verify_otp(self.request, "222222"), "invalid")
        self.assertEqual(verify_otp(self.request, "333333"), "locked")
        self.assertNotIn("otp_code_hash", self.request.session)

    @patch("base.views.generate_otp", return_value="123456")
    def test_expired_otp_is_destroyed(self, _):
        set_otp(self.request)
        self.request.session["otp_code_timestamp"] -= 301

        self.assertEqual(verify_otp(self.request, "123456"), "expired")
        self.assertNotIn("otp_code_hash", self.request.session)


@override_settings(TWO_FACTORS_AUTHENTICATION=True)
class TwoFactorMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, *, user_id=42, verified=False, verified_user_id=""):
        request = self.factory.get("/hr/")
        request.user = SimpleNamespace(pk=user_id, is_authenticated=True)
        request.session = {
            "otp_code_verified": verified,
            "mfa_verified_user_id": verified_user_id,
        }
        return request

    def test_unverified_authenticated_session_is_redirected(self):
        response = TwoFactorAuthMiddleware(lambda _: HttpResponse("ok"))(
            self._request()
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/two-factor")

    def test_verification_is_bound_to_current_user(self):
        response = TwoFactorAuthMiddleware(lambda _: HttpResponse("ok"))(
            self._request(verified=True, verified_user_id="41")
        )
        self.assertEqual(response.status_code, 302)

    def test_matching_verified_session_is_allowed(self):
        response = TwoFactorAuthMiddleware(lambda _: HttpResponse("ok"))(
            self._request(verified=True, verified_user_id="42")
        )
        self.assertEqual(response.status_code, 200)


class MfaProductionContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(__file__).resolve().parents[2]
        cls.compose = (cls.root / "docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )
        cls.template = (
            cls.root / "backend/base/templates/base/auth/two_factor_auth.html"
        ).read_text(encoding="utf-8")

    def test_production_compose_enforces_mfa_and_smtp_delivery(self):
        self.assertIn('TWO_FACTORS_AUTHENTICATION: "True"', self.compose)
        self.assertIn("EMAIL_HOST: ${EMAIL_HOST:?Set EMAIL_HOST in .env}", self.compose)
        self.assertIn('EMAIL_FAIL_SILENTLY: "False"', self.compose)
        self.assertIn(
            "DEFAULT_FROM_EMAIL: ${DEFAULT_FROM_EMAIL:?Set DEFAULT_FROM_EMAIL in .env}",
            self.compose,
        )

    def test_mfa_page_uses_only_bundled_scripts_and_hashed_session_marker(self):
        self.assertNotIn("https://", self.template)
        self.assertNotIn("http://", self.template)
        self.assertIn("request.session.otp_code_hash", self.template)
        self.assertNotIn("request.session.otp_code %}", self.template)

    def test_send_endpoint_is_post_only_and_not_threaded(self):
        from base import views

        source = inspect.getsource(views.send_otp)
        self.assertIn("@require_POST", source)
        self.assertNotIn("threading", source)
        self.assertIn("send_deployment_email", source)

        backend_source = inspect.getsource(views.send_deployment_email)
        self.assertIn("EmailBackend(", backend_source)
        self.assertIn("fail_silently=False", backend_source)
        self.assertNotIn("DynamicEmailConfiguration", backend_source)
