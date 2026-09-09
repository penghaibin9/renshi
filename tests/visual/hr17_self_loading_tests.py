"""Production HR17 JS scheduling on Chromium DOM with isolated HTTP promises.

These cases prove rendering order and failure presentation, not authentication,
MySQL, source-authority correctness or real site navigation. Actual activation
and HR17 identity readback remain in hr_account_activation_browser_tests.py.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "frontend/static/hr/js/pages/hr17-self.js"
BOOTSTRAP = {
    "identity": {"legalName": "合成加载验收教师", "staffNo": "LOAD-001", "employmentStatus": "ACTIVE"},
    "primaryStatus": {"status": "OK", "assignment": {"orgName": "合成学院", "positionName": "教师"}},
    "summary": {"availableServices": 1, "pinnedServices": 0},
    "services": [{"name": "我的合同", "service_code": "CONTRACT", "source_domain": "HR07", "route": "/hr/self/contracts/"}],
    "providerHealth": {"HR03": {"status": "OK"}},
    "registeredProviderDomains": ["HR03"], "degradedDomains": [],
    "capabilities": {"selfIdentity": True},
    "todos": [{"title": "合成待办", "status": "PENDING"}],
    "progress": [{"name": "合成进度", "status": "SUBMITTED"}],
}
RECORDS = {
    "payslips": [{"periodCode": "合成工资结果", "netAmount": "1200.00", "status": "FINALIZED"}],
    "contracts": [{"title": "合成合同摘要", "status": "SIGNED"}],
    "files": [{"title": "合成材料目录", "verificationStatus": "VERIFIED"}],
}
HARNESS = """() => {
  window.requests = [];
  window.fetch = (url, options) => new Promise((resolve, reject) => {
    const request = {url, options, resolve, reject};
    window.requests.push(request);
    options.signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')));
  });
  window.answer = (url, body, status) => {
    const request = window.requests.find(row => row.url === url);
    if (!request) throw new Error('missing isolated request');
    request.resolve({ok: status >= 200 && status < 300, json: async () => body});
  };
}"""


class SelfLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(
            headless=True, executable_path=os.getenv("HR_CHROMIUM_EXECUTABLE") or None,
        )
        cls.source = SCRIPT.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 390, "height": 844})
        self.pages = []
        self.page_errors = []

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.page_errors, [])

    def start(self, section, *, records_url="/isolated/records"):
        page = self.context.new_page()
        self.pages.append(page)
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        page.set_content(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
          <div data-module="HR17" data-section="{section}"
               data-bootstrap-url="/isolated/bootstrap" data-records-url="{records_url}">
            <section id="hr17-kpis">正在读取指标</section>
            <section id="hr17-identity">正在读取主档</section>
            <section id="hr17-health"></section><section id="hr17-caps"></section>
            <h2 id="hr17-work-title"></h2><p id="hr17-work-desc">正在读取</p>
            <div id="hr17-service-tools" hidden><input id="hr17-search">
              <select id="hr17-domain"></select></div>
            <div id="hr17-services" hidden></div><div id="hr17-rows">正在读取记录</div>
          </div></html>''')
        page.evaluate(HARNESS)
        page.add_script_tag(content=self.source)
        return page

    @staticmethod
    def answer(page, endpoint, body, status=200):
        page.evaluate("([url, body, status]) => window.answer(url, body, status)",
                      [f"/isolated/{endpoint}", body, status])

    def assert_identity(self, page):
        expect(page.locator("#hr17-identity")).to_contain_text("LOAD-001", timeout=1000)
        expect(page.locator("#hr17-kpis .hr17-kpi b").first).to_have_text("1")

    def test_non_record_workspaces_render_without_records_request(self):
        for section in ("overview", "services", "todos", "progress"):
            with self.subTest(section=section):
                page = self.start(section)
                self.answer(page, "bootstrap", BOOTSTRAP)
                self.assert_identity(page)
                self.assertEqual(page.evaluate("requests.map(r => r.url)"), ["/isolated/bootstrap"])
                expect(page.locator("#hr17-work-desc")).not_to_contain_text("正在读取")
                if section in ("overview", "services"):
                    expect(page.get_by_role("link", name="我的合同", exact=False)).to_be_visible()
                    page.locator("#hr17-search").fill("不存在的服务")
                    expect(page.locator("#hr17-services")).to_contain_text("没有符合条件")
                page.close()

    def test_slow_records_do_not_block_identity_or_become_false_empty(self):
        for section, title in (("payslips", "合成工资结果"), ("contracts", "合成合同摘要"), ("files", "合成材料目录")):
            with self.subTest(section=section):
                page = self.start(section)
                self.answer(page, "bootstrap", BOOTSTRAP)
                self.assert_identity(page)
                expect(page.locator("#hr17-rows")).to_contain_text("正在读取本人记录")
                expect(page.locator("#hr17-rows")).not_to_contain_text("暂不可用")
                self.answer(page, "records", RECORDS)
                expect(page.locator("#hr17-rows")).to_contain_text(title)
                expect(page.locator("#hr17-rows")).not_to_contain_text("正在读取")
                page.close()

    def test_records_arriving_first_are_retained_until_identity_is_known(self):
        page = self.start("contracts")
        self.answer(page, "records", RECORDS)
        expect(page.locator("#hr17-rows")).not_to_contain_text("合成合同摘要")
        self.answer(page, "bootstrap", BOOTSTRAP)
        self.assert_identity(page)
        expect(page.locator("#hr17-rows")).to_contain_text("合成合同摘要")

    def test_denied_or_failed_records_keep_identity_and_report_unavailable(self):
        for status in (403, 500):
            with self.subTest(status=status):
                page = self.start("payslips")
                self.answer(page, "bootstrap", BOOTSTRAP)
                self.answer(page, "records", {"error": {"message": "isolated failure"}}, status)
                self.assert_identity(page)
                expect(page.locator("#hr17-rows")).to_contain_text("暂不可用")
                expect(page.locator("#hr17-rows")).not_to_contain_text("当前没有可展示的正式工资结果")
                page.close()

    def test_malformed_record_items_are_not_an_unhandled_render_failure(self):
        for records_first in (False, True):
            with self.subTest(records_first=records_first):
                page = self.start("files")
                if records_first:
                    self.answer(page, "records", {"files": [None]})
                    self.answer(page, "bootstrap", BOOTSTRAP)
                else:
                    self.answer(page, "bootstrap", BOOTSTRAP)
                    self.answer(page, "records", {"files": [None]})
                self.assert_identity(page)
                expect(page.locator("#hr17-rows")).to_contain_text("暂不可用")
                page.close()

    def test_confirmed_empty_records_remain_a_distinct_state(self):
        page = self.start("contracts")
        self.answer(page, "bootstrap", BOOTSTRAP)
        self.answer(page, "records", {"contracts": []})
        expect(page.locator("#hr17-rows")).to_contain_text("当前没有可展示的本人合同")
        expect(page.locator("#hr17-rows")).not_to_contain_text("暂不可用")

    def test_late_records_cannot_replace_a_failed_bootstrap(self):
        page = self.start("contracts")
        self.answer(page, "bootstrap", {}, 403)
        expect(page.locator("#hr17-identity")).to_contain_text("读取失败")
        self.answer(page, "records", RECORDS)
        expect(page.locator("#hr17-rows")).to_contain_text("读取失败")
        expect(page.locator("#hr17-rows")).not_to_contain_text("合成合同摘要")

    def test_optional_records_url_and_duplicate_mount_do_not_block_home(self):
        page = self.start("overview", records_url="")
        page.add_script_tag(content=self.source)
        self.answer(page, "bootstrap", BOOTSTRAP)
        self.assert_identity(page)
        self.assertEqual(page.evaluate("requests.length"), 1)
        self.assertEqual(page.evaluate("requests[0].options.credentials"), "same-origin")


if __name__ == "__main__":
    unittest.main()
