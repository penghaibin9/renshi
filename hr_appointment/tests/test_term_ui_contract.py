from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Hr14TermUiContractTests(SimpleTestCase):
    def test_workspace_term_compiles_and_uses_canonical_routes(self):
        template = get_template("hr_appointment/workspace_term.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("appointment-facts/", source)
        self.assertIn("/renewals/", source)
        self.assertIn("/term-changes/", source)
        self.assertIn("/decision/", source)
        self.assertIn("/expiring/", source)
        self.assertNotIn("Term UUID", source)
        self.assertNotIn("AppointmentFact UUID", source)

    def test_term_ui_never_equates_approval_with_effect(self):
        template = get_template("hr_appointment/workspace_term.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("批准 ≠ 已生效", source)
        self.assertIn("尚未形成新的正式 AppointmentFact / Term", source)
        self.assertIn("HR03/正式聘任事实尚未生效", source)
        self.assertIn("新的 PositionAppointmentFact / AppointmentTerm 与 HR03 Assignment effect receipt", source)
