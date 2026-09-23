"""Real Chromium smoke test for the source-only HR usability component.

This does not claim backend business-flow acceptance. It verifies that the exact
CSS/JS shipped by the product behaves in a real Chromium DOM while the full
Django/MySQL runtime is unavailable in the current sandbox.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "tests/artifacts/hr-usability-static"
HTML = ARTIFACT / "harness.html"
CSS_PATH = ROOT / "frontend/static/hr/css/hr-guide.css"
JS_PATH = ROOT / "frontend/static/hr/js/core/hr-guide.js"
API_JS_PATH = ROOT / "frontend/static/hr/js/core/api-client.js"
SMART_JS_PATH = ROOT / "frontend/static/hr/js/core/hr-smart-fill.js"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    HTML.write_text(
        f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">
<style>
:root{{--hr-primary-600:#2563eb;--hr-primary-700:#1d4ed8;--hr-primary-50:#eff6ff;--hr-text-900:#0f172a;--hr-text-700:#334155;--hr-text-500:#64748b;--hr-surface:#fff;--hr-canvas:#f6f8fc;--hr-border:#e2e8f0;}}
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f6f8fc;color:#0f172a}}
.hr-v2-page{{max-width:900px;margin:40px auto;padding:24px;background:#fff;border:1px solid #e2e8f0;border-radius:16px}}
label{{display:block;margin:12px 0}} label>span:first-child{{display:inline-block;width:100px}} input,select{{padding:8px;border:1px solid #cbd5e1;border-radius:8px}}
</style>
</head>
<body><main class=\"hr-v2-page\" data-module=\"HR05\" data-section=\"prehires\">
<h1>入职单详情</h1><p id=\"sensitive\">测试敏感文本：张三 430000000000000000 18800000000</p>
<form id=\"demo-form\">
<label><span>人员编号</span><input name=\"code\" required></label>
<label><span>到岗日期</span><input name=\"date\" type=\"date\" required></label>
<label><span>组织</span><select name=\"org\" required><option value=\"\">请选择</option><option value=\"1\">计算机学院</option></select></label>
<label><span>备注</span><textarea name=\"note\"></textarea></label>
<button type=\"submit\">保存</button>
</form>
</main></body></html>""",
        encoding="utf-8",
    )

    evidence: dict[str, object] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_content(HTML.read_text("utf-8"), wait_until="load")
        page.add_style_tag(content=CSS_PATH.read_text("utf-8"))
        page.add_script_tag(content=JS_PATH.read_text("utf-8"))
        page.add_script_tag(content=SMART_JS_PATH.read_text("utf-8"))
        page.wait_for_timeout(50)

        require(page.locator(".hr-guide-launcher").count() == 1, "launcher missing")
        require(page.locator(".hr-guide-form-progress").count() == 1, "form progress missing")
        require(page.locator(".hr-smart-fill-bar").count() == 1, "smart fill bar missing")
        require(page.locator(".hr-smart-optional-badge", has_text="可选").count() >= 1, "optional field badge missing")
        require(page.locator(".hr-guide-lifecycle").count() == 1, "lifecycle coach missing")
        require("1/3" in page.locator(".hr-guide-form-progress").inner_text(), "passive prefill progress incorrect")

        page.locator(".hr-guide-launcher").click()
        require(page.locator(".hr-guide-drawer.is-open").count() == 1, "drawer did not open")
        require("入职管理" in page.locator("#hr-guide-title").inner_text(), "wrong contextual module")

        page.locator(".hr-guide-search").fill("入职")
        page.wait_for_timeout(100)
        results = page.locator(".hr-guide-result").all_inner_texts()
        require(any("办理新教职工入职" in text for text in results), "task search did not find onboarding")
        require(page.locator(".hr-guide-search-journeys:not([hidden])").count() == 1, "cross-module journey did not render")
        require(
            "新教职工从录用到正常发薪" in page.locator(".hr-guide-search-journeys").inner_text(),
            "onboarding journey missing from contextual search",
        )
        require(
            page.locator('.hr-guide-search-journeys a[href="/hr/payroll/calculations/"]').count() >= 1,
            "onboarding journey does not reach payroll",
        )

        require(page.locator(".hr-guide-glossary-chip").count() >= 6, "context glossary chips missing")
        require(page.locator(".hr-guide-prompt").count() >= 20, "expanded prompt library missing")
        require("少填一点" in page.locator(".hr-guide-drawer").inner_text(), "autofill guidance section missing")
        page.locator(".hr-guide-prompt", has_text="提交前帮我核对一下还缺什么？").click()
        require("当前表单必填完成度" in page.locator(".hr-guide-answer").inner_text(), "assistant did not answer with current form completion metadata")
        page.locator(".hr-guide-glossary-chip", has_text="核验").click()
        require(
            "检查材料、身份或数据" in page.locator(".hr-guide-glossary-answer").inner_text(),
            "context glossary did not explain 核验",
        )
        page.locator(".hr-guide-search").fill("封板是什么意思")
        page.wait_for_timeout(80)
        require(page.locator(".hr-guide-glossary-results:not([hidden])").count() == 1, "glossary search did not render")
        glossary_text = page.locator(".hr-guide-glossary-results").inner_text()
        require("封板" in glossary_text and "后续不能直接改原值" in glossary_text, "封板 plain-language definition missing")
        page.locator(".hr-guide-search").fill("入职")
        page.wait_for_timeout(50)

        first_prompt = page.locator(".hr-guide-prompt").first
        prompt_text = first_prompt.inner_text()
        first_prompt.click()
        require(page.locator(".hr-guide-answer:not([hidden])").count() == 1, "prompt answer did not render")
        safe_prompt = page.evaluate("q => window.YuekeHRGuide.buildSafePrompt(q)", prompt_text)
        require("张三" not in safe_prompt, "safe prompt leaked visible staff name")
        require("430000000000000000" not in safe_prompt, "safe prompt leaked ID number")
        require("18800000000" not in safe_prompt, "safe prompt leaked phone")
        require("当前表单只提供完成度元数据" in safe_prompt, "safe prompt missing form completion metadata")
        require("不包含任何字段值" in safe_prompt, "safe prompt must declare value-free form context")

        page.keyboard.press("Escape")
        page.wait_for_timeout(220)
        require(page.locator(".hr-guide-drawer.is-open").count() == 0, "Escape did not close drawer")
        page.keyboard.press("Alt+k")
        page.wait_for_timeout(80)
        require(page.locator(".hr-guide-drawer.is-open").count() == 1, "Alt+K did not open drawer")
        page.keyboard.press("Escape")
        page.wait_for_timeout(220)

        # Smart-fill is deliberately conservative: the one unambiguous required select is
        # passively carried in before any click; other safe values still need explicit action.
        require(page.locator('select[name="org"]').input_value() == "1", "unique safe select was not passively prefilled")
        page.locator(".hr-smart-fill-bar__actions button", has_text="一键填可确定项").click()
        page.locator(".hr-smart-fill-bar__actions button", has_text="只看必填").click()
        require(page.locator('textarea[name="note"]').evaluate("el => getComputedStyle(el.closest('label')).display") == "none", "optional field was not hidden in compact mode")
        page.locator(".hr-smart-fill-bar__actions button", has_text="显示全部").click()
        page.locator('textarea[name="note"]').fill("已有补充说明")
        page.locator(".hr-smart-fill-bar__actions button", has_text="只看必填").click()
        require(page.locator('textarea[name="note"]').evaluate("el => getComputedStyle(el.closest('label')).display") != "none", "compact mode hid populated optional value")
        page.locator(".hr-smart-fill-bar__actions button", has_text="显示全部").click()

        page.locator('input[name="code"]').fill("PRE-001")
        require("2/3" in page.locator(".hr-guide-form-progress").inner_text(), "progress did not update")
        page.locator(".hr-smart-fill-bar__actions button", has_text="提交前核对").click()
        require(page.locator(".hr-smart-review").count() == 1, "pre-submit review did not open")
        review_text = page.locator(".hr-smart-review").inner_text()
        require("还缺 1 个必填项" in review_text and "到岗日期" in review_text, "pre-submit review missing required-field guidance")
        require("测试敏感文本" not in review_text and "430000000000000000" not in review_text, "pre-submit review leaked visible PII")
        page.screenshot(path=str(ARTIFACT / "hr05-pre-submit-review-real-chromium.png"), full_page=True)
        page.locator(".hr-smart-review__close").click()
        page.locator('button[type="submit"]').click()
        page.wait_for_timeout(50)
        require(page.locator(".hr-guide-invalid-summary:not([hidden])").count() == 1, "invalid summary not shown")
        invalid_text = page.locator(".hr-guide-invalid-summary").inner_text()
        require("还有 1 项需要补充" in invalid_text, "invalid count incorrect")

        page.add_script_tag(content=API_JS_PATH.read_text("utf-8"))
        timeout_guidance = page.evaluate(
            """() => window.HrApi.apiErrorToGuidance({code:'TIMEOUT_OR_ABORTED', requestId:'REQ-001'})"""
        )
        require("避免重复提交" in timeout_guidance["action"], "timeout guidance is not action-oriented")
        require(timeout_guidance["requestId"] == "REQ-001", "requestId not preserved in guidance")

        # Re-open the real shipped drawer for a visual evidence screenshot.
        page.locator(".hr-guide-launcher").click()
        page.wait_for_timeout(80)
        page.screenshot(path=str(ARTIFACT / "hr05-guide-drawer-real-chromium.png"), full_page=True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(220)
        page.screenshot(path=str(ARTIFACT / "hr05-guide-real-chromium.png"), full_page=True)
        evidence = {
            "browser": "Chromium",
            "launcher": "PASS",
            "cross_module_journey": "PASS",
            "context_module": "HR05 入职管理",
            "task_search": "PASS",
            "prompt_answer": "PASS",
            "safe_prompt_no_visible_pii": "PASS",
            "keyboard_shortcut": "PASS",
            "form_progress": "PASS",
            "invalid_summary": "PASS",
            "action_oriented_error_guidance": "PASS",
            "context_glossary": "PASS",
            "natural_language_glossary_search": "PASS",
            "expanded_prompt_library": "PASS",
            "autofill_guidance": "PASS",
            "smart_fill_passive_unique_option": "PASS",
            "prompt_count_per_module_min": 20,
            "pre_submit_review": "PASS",
            "optional_field_labels": "PASS",
            "compact_required_only_mode": "PASS",
            "fourteen_step_lifecycle": "PASS",
            "page_errors": errors,
        }
        require(not errors, "page errors: " + " | ".join(errors))

        home = browser.new_page(viewport={"width": 1440, "height": 1000})
        home_errors: list[str] = []
        home.on("pageerror", lambda exc: home_errors.append(str(exc)))
        home.set_content(
            """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'></head><body>
            <main class='hr-v2-page hr-home' data-hr-page='overview' data-module='HR01'>
              <h1>人事工作台</h1>
              <section class='hr-v2-conclusions'><article>我的待办</article></section>
              <section><h2>人事业务导航</h2></section>
            </main></body></html>""",
            wait_until="load",
        )
        home.add_style_tag(content=CSS_PATH.read_text("utf-8"))
        home.add_script_tag(content=JS_PATH.read_text("utf-8"))
        home.add_script_tag(content=SMART_JS_PATH.read_text("utf-8"))
        home.wait_for_timeout(50)
        require(home.locator(".hr-guide-home").count() == 1, "HR01 task-first finder missing")
        require(home.locator(".hr-guide-lifecycle").count() == 1, "HR01 lifecycle coach missing")
        full_lifecycle = home.evaluate("() => window.YuekeHRGuide.fullLifecycle")
        require(full_lifecycle and len(full_lifecycle["steps"]) == 14, "full lifecycle must contain 14 steps")
        home.locator(".hr-guide-home__search").fill("入职")
        home.wait_for_timeout(80)
        require(
            home.locator('.hr-guide-home__result[href="/hr/onboarding/prehires"]').count() >= 1,
            "HR01 入职 search did not resolve to HR05",
        )
        require(home.locator(".hr-guide-home__journeys:not([hidden])").count() == 1, "HR01 complete journey missing")
        require(
            "新教职工从录用到正常发薪" in home.locator(".hr-guide-home__journeys").inner_text(),
            "HR01 onboarding journey title missing",
        )
        home.locator(".hr-guide-home__chip", has_text="退休").click()
        home.wait_for_timeout(50)
        require(
            home.locator('.hr-guide-home__result[href="/hr/exit/retirement-precheck/"]').count() >= 1,
            "HR01 退休 chip did not resolve to retirement precheck",
        )
        retirement_results = home.locator(".hr-guide-home__result").all_inner_texts()
        require(
            all("查看今天待办" not in text and "查看人事风险预警" not in text for text in retirement_results),
            "query leaked unrelated HR01 tasks due to module preference",
        )
        journey_cases = [
            ("新教师入职", "/hr/onboarding/prehires", "新教职工从录用到正常发薪"),
            ("换部门", "/hr/changes/transfers", "教师校内调动/转岗"),
            ("续合同", "/hr/contracts/signing/", "合同到期续签"),
            ("评职称", "/hr/titles/applications/", "职称评审到岗位聘任"),
            ("离职", "/hr/exit/cases/", "退休/离校完整办理"),
            ("培训", "/hr/development/plans", "教师发展到年度考核"),
        ]
        for query, expected_route, expected_journey in journey_cases:
            home.locator(".hr-guide-home__search").fill(query)
            home.wait_for_timeout(60)
            require(
                home.locator(f'.hr-guide-home__result[href="{expected_route}"]').count() >= 1,
                f"{query} did not resolve to {expected_route}",
            )
            require(
                expected_journey in home.locator(".hr-guide-home__journeys").inner_text(),
                f"{query} did not surface journey {expected_journey}",
            )
        home.locator(".hr-guide-home__search").fill("新教师入职")
        home.wait_for_timeout(60)
        home.screenshot(path=str(ARTIFACT / "hr01-task-first-real-chromium.png"), full_page=True)
        require(not home_errors, "HR01 page errors: " + " | ".join(home_errors))
        evidence["hr01_task_first_search"] = "PASS"
        evidence["hr01_common_task_chips"] = "PASS"
        evidence["hr01_cross_module_journey"] = "PASS"
        evidence["colloquial_query_aliases"] = "PASS"
        evidence["six_high_frequency_journeys"] = "PASS"
        home.close()
        browser.close()

    (ARTIFACT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HR usability real Chromium smoke: PASS")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
