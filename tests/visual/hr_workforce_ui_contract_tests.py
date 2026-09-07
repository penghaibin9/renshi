"""Production workforce DOM/CSS/JS with isolated HTTP; not MySQL/UAT evidence."""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
API = "/api/v1/hr/home/workforce/"
DIMENSIONS = ("personnel_category", "department", "job_position", "gender", "age_group")


def distribution(dimension, buckets=None, status="OK"):
    return {"status": status, "dataBasis": "AUTHORITATIVE_EFFECTIVE_FACT", "scope": {"type": "SCHOOL"},
            "asOf": "2026-09-07", "message": "等待正式来源",
            "data": {"dimension": dimension, "buckets": buckets if buckets is not None else [{"label": dimension, "count": 12}]}}


def summary():
    return {"status": "PARTIAL", "dataBasis": "AUTHORITATIVE_EFFECTIVE_FACT", "scope": {"type": "SCHOOL"},
            "asOf": "2026-09-07", "data": {"sections": {}, "conclusions": [
                {"key": "headcount", "label": "在岗教职工", "status": "OK", "value": 18},
                {"key": "fullTimeTeacher", "label": "专任教师", "status": "UNAVAILABLE", "value": None},
                {"key": "doubleTeacher", "label": "双师型", "status": "STALE", "value": 6},
                {"key": "department", "label": "当前组织", "status": "OK"},
            ]}}


class WorkforceUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.addClassCleanup(cls.runtime.stop)
        options = {"headless": True}
        if executable := os.getenv("HR_UI_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = executable
        cls.browser = cls.runtime.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def mount(self, *, width=1440, hold=(), summary_status=200, dist=None):
        page = self.browser.new_page(viewport={"width": width, "height": 1000})
        self.addCleanup(page.close)
        # This new template's content block is literal HTML except static URLs.
        # Removing only loader tags is explicitly an isolated UI fixture, not a
        # claim that Django middleware/templates were run locally.
        source = (ROOT / "frontend/templates/hr/workforce.html").read_text()
        content = source.split("{% block content %}", 1)[1].split("{% endblock %}", 1)[0]
        content = re.sub(r"<link[^>]+>", "", content)
        self.assertNotIn("{%", content)
        page.set_content(content)
        # No host navigation or real cookie access in this isolated DOM test.
        page.evaluate("Object.defineProperty(document, 'cookie', {get:()=>'', configurable:true})")
        for filename in ("hr-tokens.css", "hr-components.css", "hr-v2.css", "hr-workforce.css"):
            page.add_style_tag(path=str(ROOT / "frontend/static/hr/css" / filename))
        page.evaluate("""config => {
          window.requests=[]; window.pending=[]; window.hold=config.hold;
          window.responses=config.responses; window.summaryStatus=config.summaryStatus;
          window.respond=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
          window.fetch=(url,options)=>{
            const target=new URL(url,'https://isolated.invalid');
            const key=target.pathname.endsWith('/summary')?'summary':target.searchParams.get('dimension');
            window.requests.push({path:target.pathname,key,method:options.method});
            if(window.hold.includes(key)) return new Promise((resolve,reject)=>window.pending.push({key,resolve,reject}));
            return Promise.resolve(window.respond(window.responses[key], key==='summary'?window.summaryStatus:200));
          };
        }""", {"hold": list(hold), "summaryStatus": summary_status,
                "responses": {"summary": summary(), **{d: distribution(d, dist) for d in DIMENSIONS}}})
        page.add_script_tag(path=str(ROOT / "frontend/static/hr/js/core/api-client.js"))
        page.add_script_tag(path=str(ROOT / "frontend/static/hr/js/pages/workforce.js"))
        return page

    def test_mounts_exist_and_distribution_does_not_wait_for_summary(self):
        page = self.mount(hold=("summary",))
        expect(page.locator("#hr-workforce-tabs button")).to_have_count(5)
        expect(page.locator("#hr-workforce-dist .wf-table")).to_have_count(1)
        expect(page.locator("#hr-workforce-summary")).to_have_attribute("aria-busy", "true")
        self.assertTrue(all(x["path"].startswith(API) for x in page.evaluate("requests")))

    def test_all_dimensions_and_keyboard_keep_focus_and_exact_response(self):
        page = self.mount()
        for dimension in DIMENSIONS:
            button = page.locator(f'[data-dim="{dimension}"]')
            button.focus(); button.press("Enter")
            expect(button).to_be_focused()
            expect(button).to_have_attribute("aria-pressed", "true")
            expect(page.locator('[data-dim][aria-pressed="true"]')).to_have_count(1)
            expect(page.locator("#hr-workforce-dist tbody th")).to_have_text([dimension])
            expect(page.locator("#hr-workforce-dist")).to_have_attribute("aria-busy", "false")

    def test_small_samples_are_not_zero_or_numeric_bars(self):
        page = self.mount(dist=[{"label": "小样本组", "count": "<5"}, {"label": "空组", "count": 0}, {"label": "公开组", "count": 18}])
        expect(page.locator(".wf-count")).to_have_text(["<5", "0", "18"])
        expect(page.locator('[data-count-kind="masked"] .wf-bar')).to_have_count(0)
        expect(page.locator('[data-count-kind="masked"]')).to_contain_text("小样本已隐藏")
        expect(page.locator(".wf-kpi strong")).to_have_text(["18", "—", "6"])
        expect(page.locator('.wf-kpi[data-state="STALE"]')).to_contain_text("待更新")

    def test_server_text_is_escaped_and_does_not_execute(self):
        text = '<img src=x onerror="window.injected=true">'
        page = self.mount(dist=[{"label": text, "count": 9}])
        expect(page.locator("#hr-workforce-dist tbody th")).to_have_text([text])
        expect(page.locator("#hr-workforce-dist img")).to_have_count(0)
        self.assertIsNone(page.evaluate("window.injected"))

    def test_late_response_cannot_replace_newer_dimension(self):
        page = self.mount()
        expect(page.locator("#hr-workforce-dist")).to_have_attribute("aria-busy", "false")
        page.evaluate("window.hold=['gender','age_group']")
        page.locator('[data-dim="gender"]').click()
        page.locator('[data-dim="age_group"]').click()
        page.evaluate("pending.find(p=>p.key==='age_group').resolve(respond(responses.age_group))")
        expect(page.locator("#hr-workforce-dist tbody th")).to_have_text(["age_group"])
        page.evaluate("pending.find(p=>p.key==='gender').resolve(respond(responses.gender))")
        expect(page.locator("#hr-workforce-dist tbody th")).to_have_text(["age_group"])
        expect(page.locator("#wf-distribution-title")).to_have_text("年龄结构 · 人数分布")

    def test_unavailable_and_invalid_payloads_never_become_zero(self):
        page = self.mount()
        for payload in (distribution("gender", status="UNAVAILABLE"), distribution("gender", [{"label": "bad", "count": {"count": 5}}])):
            page.evaluate("payload=>{window.responses.gender=payload}", payload)
            page.locator('[data-dim="gender"]').click()
            expect(page.locator("#hr-workforce-dist")).to_have_attribute("aria-busy", "false")
            expect(page.locator("#hr-workforce-dist .wf-count")).to_have_count(0)
            expect(page.locator("#hr-workforce-dist .hr-skeleton")).to_have_count(0)
            self.assertIn(page.locator("#hr-workforce-dist").get_attribute("data-state"), ("error", "unavailable"))

    def test_summary_error_does_not_disable_dimensions_and_retry_recovers(self):
        page = self.mount(summary_status=403)
        expect(page.locator("#hr-workforce-summary")).to_have_attribute("data-state", "error")
        expect(page.locator("#hr-workforce-dist .wf-table")).to_have_count(1)
        page.evaluate("window.summaryStatus=200")
        page.locator('[data-retry="summary"]').click()
        expect(page.locator(".wf-kpi strong")).to_have_text(["18", "—", "6"])

    def test_network_failure_clears_old_dimension_and_retry_uses_current_choice(self):
        page = self.mount()
        page.evaluate("window.hold=['department']")
        page.locator('[data-dim="department"]').click()
        expect(page.locator("#hr-workforce-dist .wf-table")).to_have_count(0)
        page.evaluate("pending.find(p=>p.key==='department').reject(new Error('offline'))")
        expect(page.locator("#hr-workforce-dist")).to_have_attribute("data-state", "error")
        page.evaluate("window.hold=[]")
        page.locator('[data-retry="distribution"]').click()
        expect(page.locator("#hr-workforce-dist tbody th")).to_have_text(["department"])

    def test_mobile_controls_and_table_fit_narrow_workspace(self):
        page = self.mount(width=390, dist=[{"label": "很长的学院名称用于检查移动端不遮挡人数和操作入口", "count": 11}])
        # Emulate the width after the existing mobile icon rail, not its logic.
        page.add_style_tag(content='.hr-workforce{width:326px;box-sizing:border-box;margin:0}')
        expect(page.locator("#hr-workforce-dist .wf-table")).to_have_count(1)
        for item in page.locator("#hr-workforce-tabs button").all():
            self.assertGreaterEqual(item.bounding_box()["height"], 44)
        self.assertLessEqual(page.locator('.hr-workforce').evaluate('n=>n.scrollWidth-n.clientWidth'), 1)
        out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR01-WORKFORCE-UI-UNIT"
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "mobile-isolated-ui.png"), full_page=True)


if __name__ == "__main__":
    unittest.main()
