from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from base.views import _configure_login_session


class LoginPageContractTests(SimpleTestCase):
    def setUp(self):
        self.source = (
            Path(__file__).resolve().parents[2] / "frontend" / "templates" / "login.html"
        ).read_text(encoding="utf-8")

    def test_login_page_does_not_rewrite_all_warnings_as_account_blocks(self):
        self.assertNotIn("Your login credentials are currently blocked", self.source)
        self.assertNotIn("Swal.fire", self.source)

    def test_login_page_has_no_runtime_cdn_dependency(self):
        self.assertNotIn("code.jquery.com", self.source)
        self.assertNotIn("cdn.jsdelivr.net", self.source)

    def test_login_logo_has_a_single_valid_src_attribute(self):
        self.assertIn(
            'src="{% if white_label_company.icon %}{{ white_label_company.icon.url }}',
            self.source,
        )
        self.assertNotIn('style=" opacity:.90; 200px;', self.source)

    @override_settings(LOGIN_REMEMBER_ME_SECONDS=1_209_600)
    def test_remember_me_uses_a_bounded_persistent_session(self):
        request = SimpleNamespace(session=Mock())

        _configure_login_session(request, True)

        request.session.set_expiry.assert_called_once_with(1_209_600)

    def test_unchecked_remember_me_expires_when_browser_closes(self):
        request = SimpleNamespace(session=Mock())

        _configure_login_session(request, False)

        request.session.set_expiry.assert_called_once_with(0)

    def test_active_theme_posts_the_remember_me_field(self):
        source = (
            Path(__file__).resolve().parent.parent
            / "horilla_theme"
            / "templates"
            / "login.html"
        ).read_text(encoding="utf-8")
        self.assertIn('name="remember_me"', source)
        self.assertIn("white_label_company.company", source)
        self.assertIn("white_label_company.icon.url", source)
        self.assertNotIn(">国内大学<", source)
        self.assertNotIn("jquery/jquery.min.js", source)
