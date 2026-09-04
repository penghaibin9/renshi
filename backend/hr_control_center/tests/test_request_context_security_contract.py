from pathlib import Path

from django.test import SimpleTestCase


class RequestContextSecurityContractTests(SimpleTestCase):
    def setUp(self):
        self.backend = Path(__file__).resolve().parents[2]

    def _source(self, relative):
        return (self.backend / relative).read_text(encoding="utf-8")

    def test_browser_cannot_override_school_timezone(self):
        files = (
            "hr_control_center/api/views.py",
            "hr_recruitment/api/base.py",
            "hr_onboarding/api/base.py",
            "hr_external/api/base.py",
            "hr_time/api/views.py",
            "hr_changes/api/base.py",
        )
        for relative in files:
            source = self._source(relative)
            self.assertNotIn("school_timezone=request.GET", source, relative)
            self.assertTrue(
                "school_timezone=settings.TIME_ZONE" in source
                or "school_timezone = settings.TIME_ZONE" in source,
                relative,
            )

    def test_browser_cannot_select_authority_mode(self):
        files = (
            "hr_recruitment/api/base.py",
            "hr_onboarding/api/base.py",
            "hr_external/api/base.py",
            "hr_time/api/views.py",
        )
        for relative in files:
            self.assertNotIn(
                "authority_mode=request.GET", self._source(relative), relative
            )
        self.assertIn(
            "authority_mode=get_authority_mode(tenant_id)",
            self._source("hr_onboarding/api/base.py"),
        )
        self.assertIn(
            "AuthorityService.get_mode(tenant_id)",
            self._source("hr_external/api/base.py"),
        )

    def test_context_builders_verify_selected_school_membership(self):
        files = (
            "hr_control_center/api/views.py",
            "hr_time/api/views.py",
            "hr_external/api/base.py",
            "hr_changes/api/base.py",
            "hr_qualification/api/access.py",
        )
        for relative in files:
            self.assertIn("get_allowed_company_ids", self._source(relative), relative)

    def test_hr08_endpoints_do_not_force_legacy_mode(self):
        api_root = self.backend / "hr_external" / "api"
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in api_root.glob("*.py")
        )
        self.assertNotIn(
            'make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY")',
            combined,
        )
