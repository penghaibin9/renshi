"""Actual Moment + production formatters, isolated DOM only (not MySQL)."""
import json
import os
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


class AccountDisplayUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start(); cls.addClassCleanup(cls.runtime.stop)
        args = {"headless": True}
        if path := os.getenv("HR_UI_CHROMIUM_EXECUTABLE"):
            args["executable_path"] = path
        cls.browser = cls.runtime.chromium.launch(**args); cls.addClassCleanup(cls.browser.close)

    def page(self, formats=None, malformed=False):
        page = self.browser.new_page(); self.addCleanup(page.close)
        content = "broken" if malformed else json.dumps(formats or {})
        page.set_content(f'<script type="application/json" id="account-display-formats">{content}</script>')
        page.evaluate("""() => {
          window.unexpected=[];
          window.fetch=()=>{unexpected.push('fetch');throw Error('No network expected')};
          window.$={ajax:()=>{unexpected.push('ajax');throw Error('No admin API expected')}};
          Object.defineProperty(window,'localStorage',{get(){unexpected.push('storage');throw Error('Storage blocked')}});
        }""")
        page.add_script_tag(path=str(ROOT / "frontend/static/build/js/moment.js"))
        for name in ("date_formatting.js", "time_formatting.js"):
            page.add_script_tag(path=str(ROOT / "backend/base/static/base" / name))
        return page

    def test_repeated_formatting_has_no_network_or_browser_storage(self):
        page = self.page({"dateFormat": "YYYY-MM-DD", "timeFormat": "HH:mm"})
        result = page.evaluate("""() => Array.from({length:100},()=>[dateFormatter.getFormattedDate('2026-09-08'),timeFormatter.getFormattedTime('05:34 PM')])""")
        self.assertTrue(all(row == ["2026-09-08", "17:34"] for row in result))
        self.assertEqual(page.evaluate("unexpected"), [])

    def test_new_document_uses_new_school_not_previous_formatter(self):
        for formats, expected in (({"dateFormat":"DD/MM/YYYY","timeFormat":"HH:mm"}, ["08/09/2026","17:34"]), ({"dateFormat":"YYYY/MM/DD","timeFormat":"hh:mm A"}, ["2026/09/08","05:34 PM"])):
            page = self.page(formats)
            self.assertEqual(page.evaluate("[dateFormatter.getFormattedDate('2026-09-08'),timeFormatter.getFormattedTime('05:34 PM')]"), expected)
            self.assertEqual(page.evaluate("unexpected"), [])

    def test_missing_or_malformed_projection_has_non_school_defaults(self):
        for malformed in (False, True):
            page = self.page(malformed=malformed)
            self.assertEqual(page.evaluate("[dateFormatter.dateFormat,timeFormatter.timeFormat]"), ["MMM. D, YYYY", "hh:mm A"])
            self.assertEqual(page.evaluate("unexpected"), [])

    def test_settings_preview_is_page_local_and_preserves_existing_method_contract(self):
        page = self.page({"dateFormat":"YYYY-MM-DD","timeFormat":"HH:mm"})
        page.evaluate("dateFormatter.setDateFormat('DD.MM.YYYY');timeFormatter.setTimeFormat('hh:mm A')")
        self.assertEqual(page.evaluate("[dateFormatter.getFormattedDate('08.09.2026'),timeFormatter.getFormattedTime12Hour('05:34 PM')]"), ["08.09.2026", "05:34 PM"])
        self.assertEqual(page.evaluate("unexpected"), [])
        newer = self.page({"dateFormat":"YYYY-MM-DD","timeFormat":"HH:mm"})
        self.assertEqual(newer.evaluate("[dateFormatter.dateFormat,timeFormatter.timeFormat]"), ["YYYY-MM-DD", "HH:mm"])


if __name__ == '__main__':
    unittest.main()
