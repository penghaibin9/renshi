from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from horilla.legacy_cutover_policy import LEGACY_HR_UI_SUCCESSORS


class CandidateAuthenticationRetirementTests(SimpleTestCase):
    def _source(self, relative):
        return (Path(settings.BACKEND_DIR) / relative).read_text(encoding="utf-8")

    def test_legacy_recruitment_ui_is_an_entry_adapter_only(self):
        self.assertEqual(LEGACY_HR_UI_SUCCESSORS["recruitment"], "/hr/recruitment/")

    def test_legacy_candidate_phone_authentication_cannot_be_revived(self):
        auth_source = self._source("recruitment/auth.py")
        view_source = self._source("recruitment/views/views.py")
        login_section = view_source[
            view_source.index("def candidate_login"):
            view_source.index("def candidate_logout")
        ]
        self.assertNotIn("CandidateAuthenticationBackend", auth_source)
        self.assertNotIn("authenticate(", login_section)
        self.assertNotIn('request.POST.get("phone")', login_section)
        self.assertIn('status=410', login_section)

    def test_canonical_candidate_query_is_tenant_bound_and_signed(self):
        source = self._source("hr_recruitment/public/views.py")
        section = source[source.index("def public_my_applications"):]
        self.assertIn("_read_candidate_receipt(access_token)", section)
        self.assertIn('tenant_id=receipt["tenant_id"]', section)
        self.assertIn('candidate_uid=receipt["candidate_uid"]', section)
        self.assertIn("primary_email__iexact=primary_email", section)
        self.assertIn("primary_mobile=primary_mobile", section)
