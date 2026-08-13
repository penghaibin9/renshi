from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class Hr13PublicitySellableUiContractTests(SimpleTestCase):
    def test_workspace_h_compiles_and_maps_internal_ids_to_business_labels(self):
        template = get_template("hr_title/workspace_h.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("caseLabel", source)
        self.assertIn("publicityLabel", source)
        self.assertIn("真实结果公示", source)
        self.assertIn("异议与复核", source)
        self.assertNotIn("案件 ${esc(x.application_case_id)}", source)
        self.assertNotIn("Publicity UUID", source)
        self.assertNotIn("Case UUID", source)

    def test_workspace_h_replaces_stale_authority_copy(self):
        template = get_template("hr_title/workspace_h.html")
        source = Path(template.origin.name).read_text(encoding="utf-8")

        self.assertIn("不再用申报状态冒充复核事实", source)
        self.assertIn("仅 CLOSED 且无阻断异议才允许形成正式职称结果", source)
        self.assertIn("recentPublicities", source)
        self.assertIn("recentAppeals", source)
