from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr13MaterialUiContractTests(SimpleTestCase):
    def test_live_workspace_renders_material_snapshots_not_placeholder(self):
        source = (
            Path(settings.BASE_DIR)
            / "hr_title/templates/hr_title/workspace_d.html"
        ).read_text(encoding="utf-8")

        self.assertIn("const material =", source)
        self.assertIn("setRows(material(d.recentMaterials))", source)
        self.assertIn("acceptedMaterials: '已验收材料'", source)
        self.assertIn("已验收材料冻结", source)
        self.assertNotIn("section === 'materials' || section === 'appeals'", source)

    def test_appeal_workspace_reads_independent_appeal_facts(self):
        source = (
            Path(settings.BASE_DIR)
            / "hr_title/templates/hr_title/workspace_d.html"
        ).read_text(encoding="utf-8")

        self.assertIn("if (section === 'appeals')", source)
        self.assertIn("d.recentAppeals", source)
        self.assertIn("每条异议独立留痕", source)
        self.assertNotIn("异议复核事实尚待 Authority 接通", source)
