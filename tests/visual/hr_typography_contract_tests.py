"""Browser checks for production HR font tokens, not system/DB acceptance.

Run: python tests/visual/hr_typography_contract_tests.py -v
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TOKENS = {
    "page-title": (24, 32, 700),
    "section-title": (16, 24, 700),
    "card-label": (13, 20, 600),
    "kpi-value": (28, 36, 700),
    "body": (14, 22, 400),
    "meta": (12, 18, 400),
}


class HrTypographyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        launch = {"headless": True}
        if executable := os.getenv("HR_UI_CHROMIUM_EXECUTABLE"):
            launch["executable_path"] = executable
        cls.browser = cls.playwright.chromium.launch(**launch)
        cls.addClassCleanup(cls.playwright.stop)
        cls.addClassCleanup(cls.browser.close)

    def test_all_production_font_tokens_resolve_size_weight_and_line_height(self):
        css = (ROOT / "frontend/static/hr/css/hr-tokens.css").read_text(encoding="utf-8")
        for width in (1440, 390):
            with self.subTest(viewport=width):
                page = self.browser.new_page(viewport={"width": width, "height": 900})
                try:
                    page.set_content("<main style='font: 400 10px/12px serif'></main>")
                    page.add_style_tag(content=css)
                    for name, (size, height, weight) in TOKENS.items():
                        actual = page.evaluate("""name => {
                          const node = document.createElement('div');
                          node.textContent = '学校人事 · 办理与结果 2026';
                          node.style.font = `var(--hr-font-${name})`;
                          document.querySelector('main').append(node);
                          const s = getComputedStyle(node);
                          return {size:s.fontSize, height:s.lineHeight, weight:s.fontWeight,
                                  family:s.fontFamily};
                        }""", name)
                        self.assertEqual(actual["size"], f"{size}px", name)
                        self.assertEqual(actual["height"], f"{height}px", name)
                        self.assertEqual(actual["weight"], str(weight), name)
                        self.assertIn("sans-serif", actual["family"], name)
                finally:
                    page.close()

    def test_previous_incomplete_shorthand_is_rejected_by_browser(self):
        page = self.browser.new_page()
        try:
            self.assertFalse(page.evaluate("CSS.supports('font', '24px/32px 700')"))
            self.assertTrue(page.evaluate("CSS.supports('font', '700 24px/32px sans-serif')"))
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
