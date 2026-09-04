from pathlib import Path

from django.template.loader import get_template
from django.test import TestCase


class Hr13PanelUiContractTests(TestCase):
    def test_workspace_f_compiles_and_uses_canonical_authorities(self):
        template = get_template("hr_title/workspace_f.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("/api/hr/v1/staff?", source)
        self.assertIn("/api/v1/hr/titles/applications/", source)
        self.assertIn("/review-rounds/", source)
        self.assertIn("/assignments/", source)
        self.assertIn("/respond/", source)
        self.assertIn("/ballots/", source)
        self.assertIn("/close/", source)
        self.assertNotIn("Staff UUID", source)
        self.assertNotIn("placeholder=\"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\"", source)

    def test_panel_ui_keeps_fail_closed_staff_provider_copy(self):
        template = get_template("hr_title/workspace_f.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("没有名册权限时不会退化成手填内部标识", source)
        self.assertIn("不允许手填身份绕过正式名册", source)
        self.assertIn("评议票提交后不可原地修改", source)
        self.assertIn("data-conflict-note", source)
        self.assertNotIn("window.prompt", source)
