"""Production CSS/JS unit checks in Chromium; isolated DOM/transport only."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


class HrPolishContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.addClassCleanup(cls.runtime.stop)
        options = {"headless": True}
        if executable := os.getenv("HR_UI_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = executable
        cls.browser = cls.runtime.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def test_seven_metric_layouts_do_not_orphan_desktop_or_overflow_mobile(self):
        for prefix, grid, css_file in (("hr13c", "hr13c-kpis", "hr13-title.css"), ("hr15", "hr15-kpis", "hr15-payroll.css")):
            for width, expected_rows in ((1440, 1), (1024, 2), (390, 4)):
                with self.subTest(module=prefix, width=width):
                    page = self.browser.new_page(viewport={"width": width, "height": 1000})
                    try:
                        page.set_content(f'<main class="hr-v2-page" style="max-width:100%;box-sizing:border-box"><section class="{grid}">' + ''.join(f'<article class="{prefix}-kpi"><span>正式结果与历史对账</span><b>{i}</b><em>按本校有效版本核对</em></article>' for i in range(7)) + '</section><button>确认办理</button></main>')
                        for filename in ("hr-tokens.css", "hr-v2.css", css_file):
                            page.add_style_tag(path=str(ROOT / "frontend/static/hr/css" / filename))
                        rects = page.locator(f'.{grid} > article').evaluate_all("nodes=>nodes.map(n=>{let r=n.getBoundingClientRect();return {top:Math.round(r.top),right:r.right,left:r.left}})")
                        self.assertEqual(len(set(r["top"] for r in rects)), expected_rows)
                        self.assertTrue(all(r["left"] >= 0 and r["right"] <= width for r in rects))
                        if width == 390:
                            self.assertGreaterEqual(page.locator('button').bounding_box()['height'], 44)
                    finally:
                        page.close()

    def test_overview_fast_regions_render_without_slow_source(self):
        page = self.browser.new_page()
        try:
            page.set_content(''.join(f'<section id="{name}"><div class="hr-skeleton">正在读取</div></section>' for name in (
                'hr-metric-strip', 'hr-priority-todos', 'hr-priority-risks', 'hr-priority-data', 'hr-todo-summary', 'hr-risk-summary', 'hr-quick-actions')))
            page.evaluate("""() => {
              window.requests={};window.HrApi={apiErrorToMessage:()=> '来源读取失败',
                request:path=>new Promise((resolve,reject)=>{window.requests[path]={resolve,reject}})};
            }""")
            page.add_script_tag(path=str(ROOT / 'frontend/static/hr/js/pages/overview.js'))
            page.evaluate("requests['/api/hr/v1/home/todos/summary'].resolve({data:{total:3,overdue:1,today:2}})")
            expect(page.locator('#hr-priority-todos')).to_contain_text('1 项逾期')
            expect(page.locator('#hr-priority-data .hr-skeleton')).to_have_count(1)
            page.evaluate("requests['/api/hr/v1/home/alerts/summary'].reject(new Error('offline'))")
            expect(page.locator('#hr-priority-risks')).to_contain_text('暂不可判断')
            self.assertNotIn('当前正常', page.locator('#hr-priority-risks').inner_text())
            page.evaluate("requests['/api/hr/v1/home/bootstrap'].resolve({data:{metrics:[{metricKey:'active_headcount',status:'UNAVAILABLE',value:null}],consistency:'PARTIAL'}})")
            expect(page.locator('#hr-metric-strip')).to_contain_text('数据暂不可用')
            self.assertEqual(page.locator('#hr-metric-strip .hr-kpi-value').count(), 0)
        finally:
            page.close()


if __name__ == '__main__':
    unittest.main()
