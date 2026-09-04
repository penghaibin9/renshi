from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from base.signals import (
    Fail2BanMiddleware,
    _login_cache_key,
    clear_login_failures,
    log_login_failed,
)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "login-rate-limit-tests",
        }
    },
    FAIL2BAN_MAX_RETRY=2,
    FAIL2BAN_IP_MAX_RETRY=10,
    FAIL2BAN_ATTEMPT_WINDOW=60,
    FAIL2BAN_BAN_TIME=120,
    FAIL2BAN_TRUST_X_REAL_IP=False,
)
class LoginRateLimitTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.post(
            "/login/",
            {"username": "some-user", "password": "wrong"},
            REMOTE_ADDR="192.0.2.15",
        )
        self.request.user = AnonymousUser()
        self.keys = [
            _login_cache_key("identity-attempts", self.request),
            _login_cache_key("identity-ban", self.request),
            _login_cache_key("ip-attempts", self.request),
            _login_cache_key("ip-ban", self.request),
        ]
        cache.delete_many(self.keys)

    def tearDown(self):
        cache.delete_many(self.keys)

    def test_health_request_never_requires_or_creates_session(self):
        request = self.factory.get("/health/", REMOTE_ADDR="192.0.2.15")
        request.user = AnonymousUser()
        response = Fail2BanMiddleware(lambda _request: HttpResponse("ok"))(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(hasattr(request, "session"))

    def test_failed_logins_are_shared_and_blocked_with_retry_after(self):
        log_login_failed(None, {"username": "some-user"}, self.request)
        log_login_failed(None, {"username": "some-user"}, self.request)

        response = Fail2BanMiddleware(lambda _request: HttpResponse("unexpected"))(
            self.request
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "120")
        self.assertNotIn("some-user", response.content.decode("utf-8"))

    def test_success_clears_failure_state(self):
        log_login_failed(None, {"username": "some-user"}, self.request)
        self.assertIsNotNone(cache.get(self.keys[0]))

        clear_login_failures(None, self.request, object())

        self.assertIsNone(cache.get(self.keys[0]))
        self.assertIsNone(cache.get(self.keys[1]))

    def test_one_account_ban_does_not_block_other_users_behind_same_nat(self):
        log_login_failed(None, {"username": "some-user"}, self.request)
        log_login_failed(None, {"username": "some-user"}, self.request)

        other = self.factory.post(
            "/login/",
            {"username": "another-user", "password": "correct"},
            REMOTE_ADDR="192.0.2.15",
        )
        other.user = AnonymousUser()
        response = Fail2BanMiddleware(lambda _request: HttpResponse("ok"))(other)

        self.assertEqual(response.status_code, 200)
