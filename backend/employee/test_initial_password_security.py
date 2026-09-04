from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class InitialPasswordSecurityContractTests(SimpleTestCase):
    def _source(self, relative):
        return (Path(settings.BACKEND_DIR) / relative).read_text(encoding="utf-8")

    def test_employee_creation_never_uses_phone_as_password(self):
        model_source = self._source("employee/models.py")
        view_source = self._source("employee/views.py")
        methods_source = self._source("employee/methods/methods.py")

        self.assertNotIn("password = str(self.phone)", model_source)
        self.assertNotIn("password=str(phone).strip()", view_source)
        self.assertNotIn('password=str(row["Phone"]).strip()', methods_source)
        self.assertIn("password=make_password(None)", methods_source)

    def test_import_password_finalization_is_not_fire_and_forget(self):
        source = self._source("employee/cbv/employees.py")
        self.assertIn("_set_password(records)", source)
        self.assertNotIn("threading.Thread", source)

    def test_ldap_sync_does_not_derive_password_from_telephone_number(self):
        for command in (
            "horilla_ldap/management/commands/import_ldap_users.py",
            "horilla_ldap/management/commands/import_users_to_ldap.py",
            "employee/management/commands/import_ldap_users.py",
        ):
            source = self._source(command)
            self.assertNotIn("ldap_password", source)
            self.assertNotIn("set_password", source)
            self.assertNotIn('entry.get("userPassword"', source)
            self.assertNotIn('"userPassword":', source)
