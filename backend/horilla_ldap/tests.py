from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve, reverse


class LdapStartupContractTests(SimpleTestCase):
    def test_ready_is_idempotent_and_does_not_read_database_settings(self):
        app_config = apps.get_app_config("horilla_ldap")
        original_apps = list(settings.APPS)
        try:
            settings.APPS[:] = [name for name in settings.APPS if name != "horilla_ldap"]
            with patch(
                "horilla.config.load_ldap_settings",
                side_effect=AssertionError("ready() must not query LDAP settings"),
            ):
                app_config.ready()
                app_config.ready()
            self.assertEqual(settings.APPS.count("horilla_ldap"), 1)
        finally:
            settings.APPS[:] = original_apps

    def test_ldap_settings_url_is_part_of_the_static_root_graph(self):
        url = reverse("ldap-settings")
        self.assertEqual(url, "/settings/ldap-settings/")
        self.assertEqual(resolve(url).url_name, "ldap-settings")
