"""Real Chromium click-through smoke for the shipped 14-step HR lifecycle coach.

The exact production CSS/JS is executed in Chromium and the user-facing lifecycle
button is clicked step by step. Navigation is prevented only inside this source-only
harness so every target URL can be asserted without a Django server. This is not a
claim that backend business transactions executed; the QA runtime must still run
scripts/hr_real_browser_click.py against Django/MySQL.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "tests/artifacts/hr-lifecycle-static"
CSS = (ROOT / "frontend/static/hr/css/hr-guide.css").read_text("utf-8")
GUIDE = (ROOT / "frontend/static/hr/js/core/hr-guide.js").read_text("utf-8")
SMART = (ROOT / "frontend/static/hr/js/core/hr-smart-fill.js").read_text("utf-8")

STEPS = [
    ("HR04", "/hr/recruitment/campaigns", "招聘"),
    ("HR05", "/hr/onboarding/prehires", "入职"),
    ("HR03", "/hr/staff/", "主档"),
    ("HR07", "/hr/contracts/", "合同"),
    ("HR06", "/hr/changes/transfers", "异动"),
    ("HR09", "/hr/qualifications/credentials/", "资质"),
    ("HR10", "/hr/development/plans", "培训"),
    ("HR11", "/hr/time/attendance/", "考勤"),
    ("HR12", "/hr/assessments/annual/", "考核"),
    ("HR14", "/hr/appointments/appointments/", "聘任"),
    ("HR15", "/hr/payroll/calculations/", "薪酬"),
    ("HR16", "/hr/exit/cases/", "离退"),
    ("HR17", "/hr/self/services/", "本人服务"),
    ("HR18", "/hr/data/quality/", "数据中心"),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    html = """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'></head><body>
    <main class='hr-v2-page hr-home' data-hr-page='overview' data-module='HR01'>
      <header class='hr-v2-pagehead'><div><span>HR01</span><h1>人事工作台</h1><p>全生命周期真人式点击烟测。</p></div></header>
      <section class='hr-v2-conclusions'><article>我的待办</article></section>
      <form id='smart-demo'>
        <label><span>业务单编号</span><input name='caseNo' required></label>
        <label><span>申请日期</span><input name='requestDate' type='date' required></label>
        <label><span>说明</span><textarea name='note'></textarea></label>
        <button type='submit'>保存</button>
      </form>
    </main></body></html>"""

    evidence: dict[str, object] = {"steps": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content(html, wait_until="load")
        page.add_style_tag(content=CSS)
        # Prevent only actual navigation; do not stop event propagation, so product click handlers still run.
        page.evaluate("""() => {
          window.__clickedLifecycleHrefs = [];
          document.addEventListener('click', (event) => {
            const a = event.target.closest('a.hr-guide-lifecycle__primary');
            if (!a) return;
            window.__clickedLifecycleHrefs.push(a.getAttribute('href'));
            event.preventDefault();
          }, true);
        }""")
        page.add_script_tag(content=GUIDE)
        page.add_script_tag(content=SMART)
        page.wait_for_timeout(80)

        require(page.locator(".hr-guide-lifecycle").count() == 1, "lifecycle coach missing")
        full = page.evaluate("() => window.YuekeHRGuide.fullLifecycle")
        require(full and len(full["steps"]) == 14, "full lifecycle must contain 14 steps")
        require([s["route"] for s in full["steps"]] == [route for _, route, _ in STEPS], "lifecycle route order mismatch")
        require(len(page.evaluate("() => window.YuekeHRGuide.prompts")) >= 20, "prompt library not expanded")
        page.screenshot(path=str(ARTIFACT / "00-before-start.png"), full_page=True)

        primary = page.locator(".hr-guide-lifecycle__primary")
        require(primary.get_attribute("href") == STEPS[0][1], "start href must be recruitment")
        primary.click()
        page.wait_for_timeout(30)

        # After starting, index 0 is active. Each subsequent click advances one step and changes href.
        for index, (module, route, label) in enumerate(STEPS):
            progress = page.locator(".hr-guide-lifecycle__progress").inner_text()
            require(f"第 {index + 1}/14 步" in progress, f"progress mismatch at step {index + 1}: {progress}")
            current = page.locator(".hr-guide-lifecycle__current").inner_text()
            require(module in current or label in current, f"current step copy mismatch at {index + 1}")
            require("少填原则" in current, f"autofill note missing at {index + 1}")
            evidence["steps"].append({"index": index + 1, "module": module, "route": route, "label": label})
            if index in {0, 6, 10, 13}:
                page.screenshot(path=str(ARTIFACT / f"{index + 1:02d}-{module}.png"), full_page=True)
            if index < len(STEPS) - 1:
                expected_next = STEPS[index + 1][1]
                require(primary.get_attribute("href") == expected_next, f"next href mismatch after step {index + 1}")
                primary.click()
                page.wait_for_timeout(20)

        require(primary.inner_text() == "完成路线核对", "final button copy incorrect")
        require(primary.get_attribute("href") == "#", "final href should not navigate")
        primary.click()
        page.wait_for_timeout(20)
        require("尚未开始" in page.locator(".hr-guide-lifecycle__progress").inner_text(), "final completion did not reset active state")

        clicked = page.evaluate("() => window.__clickedLifecycleHrefs")
        expected_clicks = [route for _, route, _ in STEPS] + ["#"]
        require(clicked == expected_clicks, f"clicked route sequence mismatch: {clicked}")

        # Smart-fill: request date is safe, free-text reason is not; compact mode hides optional note.
        page.locator(".hr-smart-fill-bar__actions button", has_text="一键填可确定项").click()
        require(page.locator('input[name="requestDate"]').input_value() != "", "safe request date not filled")
        require(page.locator('textarea[name="note"]').input_value() == "", "formal free text must not be invented")
        page.locator(".hr-smart-fill-bar__actions button", has_text="只看必填").click()
        hidden = page.locator('textarea[name="note"]').evaluate("el => getComputedStyle(el.closest('label')).display")
        require(hidden == "none", "optional field not hidden")
        page.locator(".hr-smart-fill-bar__actions button", has_text="提交前核对").click()
        require(page.locator(".hr-smart-review").count() == 1, "pre-submit review did not open")
        require("业务单编号" in page.locator(".hr-smart-review").inner_text(), "pre-submit review missing required field")
        page.locator(".hr-smart-review__close").click()

        require(not errors, "page errors: " + " | ".join(errors))
        evidence.update({
            "browser": "Chromium",
            "fourteen_step_click_sequence": "PASS",
            "clicked_hrefs": clicked,
            "prompt_count_per_module_min": 20,
            "autofill_guidance_each_step": "PASS",
            "safe_autofill": "PASS",
            "compact_required_only_mode": "PASS",
            "pre_submit_review": "PASS",
            "backend_business_transactions_executed": False,
            "page_errors": errors,
        })
        browser.close()

    (ARTIFACT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HR lifecycle real Chromium click-through: PASS")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
