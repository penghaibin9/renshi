from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from base.views import SettingsView
from horilla.menu import get_settings_menu


class _AllPermissionsUser:
    is_authenticated = True
    is_superuser = True

    def has_perm(self, _permission):
        return True

    def get_all_permissions(self):
        return set()


class SystemSettingsCenterContractTests(SimpleTestCase):
    def test_global_settings_entry_targets_the_live_settings_center(self):
        source = (Path(settings.FRONTEND_DIR) / "templates" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("{% url 'settings' %}", source)
        self.assertIn("aria-label=\"{% trans 'System Settings' %}\"", source)
        urls = (Path(settings.BASE_DIR) / "base" / "urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"settings/system-preferences-view/"', urls)
        self.assertIn('name="system-preferences-view"', urls)

    def test_system_preferences_does_not_render_retired_payroll_writer(self):
        template = (
            Path(settings.BASE_DIR)
            / "horilla_theme"
            / "templates"
            / "base"
            / "settings"
            / "system_preferences.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("payroll/settings/payroll_settings.html", template)
        self.assertNotIn("payroll-settings", template)

        shell = (
            Path(settings.BASE_DIR)
            / "horilla_theme"
            / "templates"
            / "settings.html"
        ).read_text(encoding="utf-8")
        self.assertIn('{% trans "System Settings" %}', shell)

    @patch(
        "base.views.get_settings_menu",
        return_value=[{"title": "考勤设置", "items": [{"url": "/settings/time/"}]}],
    )
    def test_settings_landing_uses_first_authorized_menu_item(self, _menu):
        request = RequestFactory().get("/settings/")
        view = SettingsView()
        view.setup(request)

        self.assertEqual(view.get_redirect_url(), "/settings/time/")

    @patch("base.views.get_settings_menu", return_value=[])
    def test_settings_landing_fails_closed_without_visible_items(self, _menu):
        request = RequestFactory().get("/settings/")
        view = SettingsView()
        view.setup(request)

        with self.assertRaises(PermissionDenied):
            view.get_redirect_url()

    def test_every_visible_settings_menu_url_resolves(self):
        request = type("SettingsRequest", (), {"user": _AllPermissionsUser()})()
        menu = get_settings_menu(request)

        self.assertGreater(len(menu), 0)
        resolved = [
            str(item["url"])
            for section in menu
            for item in section.get("items", [])
        ]
        self.assertGreater(len(resolved), 0)
        self.assertTrue(all(url.startswith("/") for url in resolved))
