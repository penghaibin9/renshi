"""HR09 V2 workspace static and route contracts."""

from pathlib import Path

from django.test import SimpleTestCase


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"


class Hr09WorkspaceStaticContractTests(SimpleTestCase):
    def test_shared_workspace_keeps_six_canonical_sections(self):
        template = (BACKEND_ROOT / "hr_qualification/templates/hr_qualification/workspace.html").read_text(
            encoding="utf-8"
        )
        for section in (
            "overview",
            "credentials",
            "batches",
            "applications",
            "recognitions",
            "risks",
        ):
            self.assertIn(section, template)
        self.assertIn('class="hr-v2-page hr09"', template)
        self.assertIn('json_script:"hr09-staff-options"', template)
        self.assertIn('json_script:"hr09-rule-version-options"', template)

    def test_action_layer_has_no_raw_internal_identifier_inputs(self):
        script = (FRONTEND_ROOT / "static/hr/js/pages/hr09-actions.js").read_text(encoding="utf-8")
        forbidden = (
            "Person UUID",
            "Staff UUID",
            "RulePackVersion UUID",
            "规则版本 UUID",
            'option value="CREDENTIAL_CHANGED"',
            'option value="EVIDENCE_INVALIDATED"',
            'option value="MANUAL_REVIEW"',
        )
        for value in forbidden:
            self.assertNotIn(value, script)
        self.assertIn("hr09-staff-options", script)
        self.assertIn("hr09-rule-version-options", script)
        self.assertIn("/advance", script)
        self.assertIn("/resubmit", script)

    def test_action_layer_does_not_fabricate_navigation_or_submit(self):
        script = (FRONTEND_ROOT / "static/hr/js/pages/hr09-actions.js").read_text(encoding="utf-8")
        self.assertNotIn('href="#"', script)
        self.assertNotIn("Math.random", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
