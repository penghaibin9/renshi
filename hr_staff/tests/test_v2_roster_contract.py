from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr03V2RosterContractTests(SimpleTestCase):
    """Keep the HR03 roster inside the shared product shell without weakening its runtime contract."""

    TEMPLATE = "hr_staff/templates/hr_staff/staff_list.html"
    CSS = "static/hr/css/hr03-staff.css"

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_roster_uses_shared_horilla_and_hr_v2_shell(self):
        source = self._source(self.TEMPLATE)
        self.assertIn('{% extends "index.html" %}', source)
        self.assertIn("hr/css/hr-v2.css", source)
        self.assertIn("hr/css/hr03-staff.css", source)
        self.assertIn('data-module="HR03"', source)
        self.assertIn("hr-v2-mobile-section-switcher", source)

    def test_real_roster_actions_and_dom_ids_are_preserved(self):
        source = self._source(self.TEMPLATE)
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
        source = self._source(self.TEMPLATE)
        for endpoint in (
            "/api/hr/v1/staff?",
            "/api/hr/v1/staff/export",
            "/api/hr/v1/staff/import",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, source)
        self.assertIn("/hr/staff/data-quality/", source)
        self.assertIn("/hr/onboarding/", source)

    def test_hr03_css_stays_on_flat_v2_foundation(self):
        css = self._source(self.CSS).lower()
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn("backdrop-filter", css)
