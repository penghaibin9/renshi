from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr03V2WorkspaceContractTests(SimpleTestCase):
    """Keep HR03 roster/profile inside the shared product shell without weakening runtime contracts."""

    ROSTER_TEMPLATE = "hr_staff/templates/hr_staff/staff_list.html"
    PROFILE_TEMPLATE = "hr_staff/templates/hr_staff/profile.html"
    ROSTER_CSS = "static/hr/css/hr03-staff.css"
    PROFILE_CSS = "static/hr/css/hr03-profile.css"

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_roster_and_profile_use_shared_horilla_v2_shell(self):
        for relative_path in (self.ROSTER_TEMPLATE, self.PROFILE_TEMPLATE):
            with self.subTest(template=relative_path):
                source = self._source(relative_path)
                self.assertIn('{% extends "index.html" %}', source)
                self.assertIn("hr/css/hr-v2.css", source)
                self.assertIn('data-module="HR03"', source)
                self.assertIn("hr-v2-mobile-section-switcher", source)

    def test_real_roster_actions_and_dom_ids_are_preserved(self):
        source = self._source(self.ROSTER_TEMPLATE)
        for token in (
            'id="keyword"',
            'id="status"',
            'id="category"',
            'id="searchBtn"',
            'id="rows"',
            'id="prev"',
            'id="next"',
            'id="importToggle"',
            'id="importFile"',
            'id="importValidate"',
            'id="importCommit"',
            'id="exportCurrent"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_existing_staff_api_contracts_remain_visible(self):
        roster = self._source(self.ROSTER_TEMPLATE)
        for endpoint in (
            "/api/hr/v1/staff?",
            "/api/hr/v1/staff/export",
            "/api/hr/v1/staff/import",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, roster)
        self.assertIn("/hr/staff/data-quality/", roster)
        self.assertIn("/hr/onboarding/", roster)

        profile = self._source(self.PROFILE_TEMPLATE)
        self.assertIn("/api/hr/v1/staff/${encodeURIComponent(staffId)}/profile", profile)
        for suffix in ("/assignments", "/backgrounds", "/materials", "/corrections"):
            self.assertIn(suffix, profile)

    def test_profile_boot_reads_explicit_root_asof_and_has_no_missing_asof_lookup(self):
        profile = self._source(self.PROFILE_TEMPLATE)
        self.assertIn('data-as-of="{{ as_of }}"', profile)
        self.assertIn("root.dataset.asOf", profile)
        self.assertNotIn('getElementById("asof")', profile)
        self.assertIn("Profile bootstrap 不返回完整资格事实", profile)
        self.assertIn("bootstrap 不返回高敏明文", profile)

    def test_hr03_css_stays_on_flat_v2_foundation(self):
        css = "\n".join(self._source(path).lower() for path in (self.ROSTER_CSS, self.PROFILE_CSS))
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn("backdrop-filter", css)
