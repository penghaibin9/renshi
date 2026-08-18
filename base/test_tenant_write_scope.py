from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from base.auth_backends import (
    get_write_company_id,
    resolve_company_id_for_new_record,
)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class ExplicitWriteTenantTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        self.request = SimpleNamespace(user=self.user)

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value="all")
    def test_all_scope_never_guesses_first_assignment_for_write(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value=None)
    def test_missing_tenant_never_guesses_write_company(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3, 9})
    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_allowed_company_is_preserved_for_write(
        self, selected_company, allowed_companies
    ):
        self.assertEqual(get_write_company_id(self.user), 9)
        self.assertEqual(resolve_company_id_for_new_record(self.request), 9)

    @patch("base.auth_backends.get_allowed_company_ids", return_value={3})
    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_company_outside_user_scope_is_rejected(
        self, selected_company, allowed_companies
    ):
        self.assertIsNone(get_write_company_id(self.user))
        self.assertIsNone(resolve_company_id_for_new_record(self.request))

    @patch("base.auth_backends.get_selected_company", return_value="9")
    def test_explicit_background_tenant_does_not_require_http_user(
        self, selected_company
    ):
        self.assertEqual(resolve_company_id_for_new_record(request=None), 9)
