"""Chinese activation errors retain dynamic validator rules and restore locale.

Only invitation/username lookup is isolated. The production activation view,
accept service, Django password validator and translation catalog run unchanged.
HTML rendering retains the production context processors, so these cases use
the test database and a real session backend. They stop at password rejection;
they do not claim browser navigation, CSRF or account-creation coverage.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings
from django.utils import translation

from base.account_invitation import activate_account_invitation
from hr_staff.services.account_invitation_service import AccountInvitationService


class AccountActivationLanguageTests(TestCase):
    def rejected(self, minimum, *, accept):
        invitation_id = uuid.uuid4()
        request = RequestFactory().post(
            f"/activate-account/{invitation_id}/",
            {"activation_token": "isolated-language-token", "username": "language-check",
             "password": "short", "confirm_password": "short"},
            HTTP_ACCEPT=accept,
        )
        request.user = AnonymousUser()
        # RequestFactory does not run session middleware; the real HTML context
        # reads request.session and school data even for an anonymous visitor.
        SessionMiddleware(lambda _request: None).process_request(request)
        validators = [{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": minimum},
        }]
        with override_settings(AUTH_PASSWORD_VALIDATORS=validators):
            with translation.override("en"):
                with patch.object(AccountInvitationService, "inspect", return_value=SimpleNamespace(id=invitation_id)):
                    with patch.object(AccountInvitationService, "_validate_username", return_value="language-check"):
                        response = activate_account_invitation(request, invitation_id)
                self.assertEqual(translation.get_language(), "en")
        self.assertEqual(response.status_code, 400)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        body = response.content.decode()
        self.assertNotIn("isolated-language-token", body)
        return response

    def test_json_translates_real_policy_limits_without_changing_them(self):
        for minimum in (12, 15):
            with self.subTest(minimum=minimum):
                response = self.rejected(minimum, accept="application/json")
                body = json.loads(response.content)
                self.assertFalse(body["ok"])
                message = body["errors"]["password"]
                self.assertIn("密码", message)
                self.assertIn(str(minimum), message)
                self.assertNotIn("This password", message)

    def test_regular_html_form_uses_the_same_chinese_validation(self):
        response = self.rejected(13, accept="text/html")
        self.assertContains(response, 'id="error-password"', status_code=400)
        self.assertContains(response, "13", status_code=400)
        self.assertNotContains(response, "This password", status_code=400)
