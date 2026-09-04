"""Production write guards for HR09 credentials."""

import inspect

from django.test import SimpleTestCase

from hr_qualification.api import views_credential


class CredentialMutationContractTests(SimpleTestCase):
    def test_create_locks_tenant_person_and_validates_before_save(self):
        source = inspect.getsource(views_credential.credential_create)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrPerson.objects.select_for_update()", source)
        self.assertIn("tenant_id=request.hr09_tenant_id", source)
        self.assertIn("credential.full_clean()", source)

    def test_update_checks_version_and_status_under_row_lock(self):
        source = inspect.getsource(views_credential.credential_update)

        self.assertIn("HrPersonCredential.objects.select_for_update()", source)
        self.assertIn('data["version"] != c.version', source)
        self.assertIn("CREDENTIAL_STATUS_BLOCKED", source)
        self.assertIn("c.full_clean()", source)

    def test_create_does_not_leak_internal_exception_details(self):
        source = inspect.getsource(views_credential.credential_create)

        self.assertNotIn('error_envelope("INTERNAL_ERROR", str(exc))', source)
