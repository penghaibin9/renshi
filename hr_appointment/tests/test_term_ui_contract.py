from pathlib import Path

from django.test import SimpleTestCase


class Hr14TermUiContractTests(SimpleTestCase):
    def test_workspace_term_compiles_and_uses_canonical_routes(self):
        source = Path("static/hr/js/pages/hr14-workflows.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("appointment-facts/", source)
        self.assertIn("/renewals/", source)
        self.assertIn("'term-changes'", source)
        self.assertIn("/decision/", source)
        self.assertIn("/expiring/", source)
        self.assertNotIn("Term UUID", source)
        self.assertNotIn("AppointmentFact UUID", source)
        self.assertNotIn("目标岗位ID", source)

    def test_term_ui_never_equates_approval_with_effect(self):
        source = Path("static/hr/js/pages/hr14-workflows.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("续聘和变更批准只形成治理决定", source)
        self.assertIn("已批准，待生效", source)
        self.assertIn("跨域任职变更必须取得真实回执", source)
        self.assertIn("半失败保持“生效待重试”", source)
