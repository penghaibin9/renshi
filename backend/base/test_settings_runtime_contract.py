import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import resolve

from base.settings_center import (
    DATE_FORMATS,
    TIME_FORMATS,
    ScopedCompanyListView,
)
from base.settings_visibility import settings_menu_visible


class SettingsRouteResolutionContractTests(SimpleTestCase):
    def test_legacy_public_paths_resolve_to_hardened_handlers(self):
        paths = (
            "/settings/system-preferences-view/",
            "/settings/pagination-settings-view/",
            "/settings/save-date/",
            "/settings/get-date-format/",
            "/settings/save-time/",
            "/settings/get-time-format/",
            "/settings/default-export-access/",
            "/enable-default-export-access/",
            "/settings/update-language-settings/",
            "/settings/company-view/",
            "/company-navbar/",
            "/company-list/",
            "/company-create-form/",
            "/settings/company-update/1/",
            "/company-update-form/1/",
        )
        for path in paths:
            with self.subTest(path=path):
                match = resolve(path)
                self.assertEqual(match.func.__module__, "base.settings_center")

    def test_company_table_never_uses_the_global_company_queryset(self):
        source = inspect.getsource(ScopedCompanyListView)
        self.assertIn("selected = _selected_company(self.request)", source)
        self.assertIn("Company.objects.filter(id=selected.id)", source)
        self.assertIn("/settings/company-update/{pk}/", source)
        self.assertIn("self.bulk_update = False", source)

    def test_display_format_allowlists_match_rendered_business_choices(self):
        self.assertIn("YYYY-MM-DD", DATE_FORMATS)
        self.assertIn("DD/MM/YYYY", DATE_FORMATS)
        self.assertIn("HH:mm:ss", TIME_FORMATS)
        self.assertIn("hh:mm A", TIME_FORMATS)
        self.assertNotIn("<script>", DATE_FORMATS)
        self.assertNotIn("25:99", TIME_FORMATS)


class SettingsGearVisibilityContractTests(SimpleTestCase):
    def test_gear_uses_the_permission_filtered_settings_registry(self):
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True),
        )
        with patch(
            "horilla.menu.get_settings_menu",
            return_value=[{"title": "System Preferences"}],
        ) as menu:
            self.assertTrue(settings_menu_visible({"request": request}))
        menu.assert_called_once_with(request)

    def test_gear_is_hidden_without_registry_items(self):
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True),
        )
        with patch("horilla.menu.get_settings_menu", return_value=[]):
            self.assertFalse(settings_menu_visible({"request": request}))

    def test_gear_is_hidden_for_anonymous_or_missing_request(self):
        self.assertFalse(settings_menu_visible({}))
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=False),
        )
        self.assertFalse(settings_menu_visible({"request": request}))
