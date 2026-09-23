"""Static contract gate for the HR in-app guidance/usability layer.

This gate intentionally checks source structure only. Runtime browser behavior is
covered by scripts/hr_usability_static_browser.py and, in QA, by the real Django
browser flow.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend/templates/index.html"
JS = ROOT / "frontend/static/hr/js/core/hr-guide.js"
SMART_JS = ROOT / "frontend/static/hr/js/core/hr-smart-fill.js"
CSS = ROOT / "frontend/static/hr/css/hr-guide.css"
REAL_BROWSER = ROOT / "scripts/hr_real_browser_click.py"
LIFECYCLE_BROWSER = ROOT / "scripts/hr_lifecycle_real_chromium.py"
API_CLIENT = ROOT / "frontend/static/hr/js/core/api-client.js"
EMPTY_STATE = ROOT / "frontend/templates/hr/components/empty_state.html"
ERROR_STATE = ROOT / "frontend/templates/hr/components/error_state.html"
UNAVAILABLE_STATE = ROOT / "frontend/templates/hr/components/unavailable_state.html"
PERMISSION_GUARD = ROOT / "frontend/templates/hr/components/permission_guard.html"
HR02_SEED = ROOT / "backend/hr_structure/management/commands/seed_hr02_defaults.py"
HR02_WORKSPACE = ROOT / "frontend/templates/hr/structure/workspace.html"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    index = INDEX.read_text("utf-8")
    js = JS.read_text("utf-8")
    css = CSS.read_text("utf-8")
    smart_js = SMART_JS.read_text("utf-8")
    api = API_CLIENT.read_text("utf-8")
    real_browser = REAL_BROWSER.read_text("utf-8")
    lifecycle_browser = LIFECYCLE_BROWSER.read_text("utf-8")
    empty_state = EMPTY_STATE.read_text("utf-8")
    error_state = ERROR_STATE.read_text("utf-8")
    unavailable_state = UNAVAILABLE_STATE.read_text("utf-8")
    permission_guard = PERMISSION_GUARD.read_text("utf-8")
    hr02_seed = HR02_SEED.read_text("utf-8")
    hr02_workspace = HR02_WORKSPACE.read_text("utf-8")

    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))
        require(condition, name)

    check("master template loads hr-guide.css", "hr/css/hr-guide.css" in index)
    check("master template loads hr-guide.js", "hr/js/core/hr-guide.js" in index)
    check("master template loads hr-smart-fill.js", "hr/js/core/hr-smart-fill.js" in index)
    check("guide activates only on HR module pages", 'querySelector(".hr-v2-page[data-module]' in js)
    check("task search exists", "我要办什么" in js and "scoreTask" in js)
    check("keyboard shortcut Alt+K exists", "event.altKey" in js and '=== "k"' in js)
    check("slash shortcut exists", 'event.key === "/"' in js)
    check("form completion helper exists", "表单完成度" in js and "input[required]" in js)
    check("invalid-field summary exists", "还有 ${invalid.length} 项需要补充" in js)
    check("first-use onboarding exists", "第一次使用？不用记菜单" in js)
    check("safe prompt builder exists", "buildSafePrompt" in js)
    check("safe prompt excludes sensitive fields by policy", "身份证号" in js and "工资" in js and "附件正文" in js)
    check("assistant does not pretend to decide formal states", "正式审批、认定、考核、薪酬和人事结论仍由后端" in js)
    check("dialog semantics exist", 'setAttribute("role", "dialog")' in js and 'aria-modal' in js)
    check("focus trap exists", 'event.key !== "Tab"' in js and "focusables" in js)
    check("reduced motion is supported", "prefers-reduced-motion" in css)
    check("mobile drawer is supported", "width: 100vw" in css)
    check("HR01 task-first finder exists", "mountHomeTaskFinder" in js and "不用先学 HR01～HR18" in js)
    check("HR01 finder has common task chips", all(token in js for token in ["合同续签", "资质到期", "工资核算", "接口同步"]))
    check("action-oriented API guidance exists", "apiErrorToGuidance" in api and "先刷新业务状态" in api)
    check("timeout warns against duplicate submit", "避免重复提交" in api)
    check("version conflict tells user to refresh and review", "刷新页面并核对最新状态" in api)
    check("real QA browser asserts usability assistant", "check_usability_guide" in real_browser)
    check("cross-module guided routes exist", "const JOURNEYS" in js and "完整办理路线" in js)
    check("guided routes do not infer completion", "不代表任何步骤已完成" in js)
    check("full 14-step lifecycle coach exists", "employee-lifecycle-full" in js and "一条线办完 · 14 个核心环节" in js)
    lifecycle_routes = [
        "/hr/recruitment/campaigns", "/hr/onboarding/prehires", "/hr/staff/", "/hr/contracts/",
        "/hr/changes/transfers", "/hr/qualifications/credentials/", "/hr/development/plans",
        "/hr/time/attendance/", "/hr/assessments/annual/", "/hr/appointments/appointments/",
        "/hr/payroll/calculations/", "/hr/exit/cases/", "/hr/self/services/", "/hr/data/quality/",
    ]
    check("full lifecycle contains exact requested route order", all(route in js for route in lifecycle_routes))
    check("lifecycle progress is resumable but not business completion", "yueke.hr.guide.lifecycle.v1" in js and "只记录导航和核对进度" in js)
    check("recent work shortcuts exist", "最近办理" in js and "recentTasks" in js and "clearRecent" in js)
    check("colloquial search aliases exist", "QUERY_ALIASES" in js and all(token in js for token in ["换部门", "续合同", "证书过期", "工资单", "离职", "新入职怎么办", "退休怎么办", "我想改信息"]))
    check("journey catalog includes high-frequency lifecycle work", all(token in js for token in ["新教职工从录用到正常发薪", "教师校内调动/转岗", "退休/离校完整办理", "职称评审到岗位聘任"]))
    check("plain-language HR glossary exists", "const GLOSSARY" in js and "术语大白话" in js and "看懂系统里的词" in js)
    check("glossary explicitly distinguishes submit from effective state", "提交成功不等于审批通过或业务生效" in js)
    check("glossary explains unavailable is not zero", "它不等于 0" in js)
    check("glossary explains frozen results and correction", "封板" in js and "更正或调整流程" in js)
    check("glossary explains idempotency", "幂等" in js and "不应重复创建或重复扣减数据" in js)
    check("all HR modules have contextual glossary terms", all(f"{code}: [" in js for code in [f"HR{i:02d}" for i in range(1, 19)]))
    check("glossary search strips natural question wording", "是什么意思|什么意思|什么叫|含义|怎么理解" in js)
    check("empty state explains what to do next", "检查筛选条件" in empty_state and "对应业务入口" in empty_state)
    check("error state gives retry and escalation guidance", "保留下面的请求编号" in error_state and "避免反复提交" in error_state)
    check("unavailable state is not presented as zero", "这不等于 0" in unavailable_state and "数据源或接口" in unavailable_state)
    check("all modules describe safe carry-forward/autofill boundaries", "const WORKFLOW_AUTOFILL" in js and all(f"{code}: [" in js[js.index("const WORKFLOW_AUTOFILL"):js.index("const moduleCode")] for code in [f"HR{i:02d}" for i in range(1, 19)]))
    generic_block = js[js.index("const GENERIC_PROMPTS"):js.index("const WORKFLOW_AUTOFILL")]
    check("at least 16 generic low-learning-cost prompts", len(re.findall(r'^\s*"[^"\n]+",?$', generic_block, flags=re.M)) >= 16)
    extra_prompt_block = js[js.index("const MODULE_EXTRA_PROMPTS"):js.index("const GENERIC_PROMPTS")]
    check("all 18 modules have extra task-specific low-learning-cost prompts", all(f"{code}: [" in extra_prompt_block for code in [f"HR{i:02d}" for i in range(1, 19)]))
    check("extra prompt library contributes at least 54 module-specific prompts", len(re.findall(r'"[^"\n]+？"', extra_prompt_block)) >= 54)
    check("return/failure prompt tells user to change only failed content", "已核验且没有变化的字段不要重复填写" in js)

    check("smart fill exposes one-click safe autofill", "一键填可确定项" in smart_js and "safeAutofill" in smart_js)
    check("smart fill has non-blocking pre-submit review", "提交前核对" in smart_js and "showReview" in smart_js and "hr-smart-review" in css)
    check("pre-submit review never prints sensitive values", "只显示字段名称和完成情况" in smart_js and "不展示身份证、工资、联系方式、附件等敏感值" in smart_js)
    check("smart fill distinguishes existing values from carried values", '"已有值"' in smart_js and '"已带入"' in smart_js)
    check("compact mode keeps populated optional fields visible", "isEmptyOptional" in smart_js and "!hasValue(control)" in smart_js)
    check("optional fields are labeled in plain language", "hr-smart-optional-badge" in smart_js and "可选" in smart_js)
    check("assistant safe prompt includes completion metadata without values", "当前表单只提供完成度元数据" in js and "不包含任何字段值" in js)
    check("assistant answers submit review and shortest-change questions", "提交前核对" in js and "只想改一项" in js)
    check("smart fill passively carries unambiguous server/unique values", "passivePrefill" in smart_js and "系统带入" in smart_js)
    check("smart fill defaults complex forms to required-only mode", "canDefaultCompact" in smart_js and "已默认进入简洁模式" in smart_js)
    check("smart fill has required-only compact mode", "只看必填" in smart_js and "hr-smart-optional-hidden" in smart_js)
    check("smart fill can use explicit server prefill", "dataset.prefillValue" in smart_js)
    check("smart fill can choose a single required option", "options.length === 1" in smart_js)
    check("smart fill can safely fill current year", "YEAR_PATTERN" in smart_js and "getFullYear" in smart_js)
    check("smart fill can generate candidate business numbers", all(token in smart_js for token in ["REC", "HT", "POL", "compactStamp"]))
    check("smart fill refuses sensitive/formal conclusions", all(token in smart_js for token in ["身份证", "工资", "审批意见", "考核结论", "离退原因"]))
    datetime_line = next(line for line in smart_js.splitlines() if "SAFE_DATETIME_PATTERN" in line and "const" in line)
    check("arrival time is not guessed by smart fill", "实际到校时间" not in datetime_line)
    check("formal effective dates are not guessed", "生效日期" in smart_js and "不建议系统自动替你决定" in smart_js)
    check("position categories are guidance not invented school policy", "管理岗位、专业技术岗位、工勤技能岗位" in smart_js and "本校仍以已生效配置为准" in smart_js)
    check("official public-institution job categories are already built into HR02", all(token in hr02_workspace for token in ["专业技术岗", "管理岗", "工勤技能岗", "特设岗位"]))
    check("HR02 ships generic grade templates instead of free-text grade entry", all(token in hr02_seed for token in ["专业技术岗位 13 级", "管理岗位 10 级", "工勤技能岗位 5 级"]))
    check("built-in grade tip keeps school policy authoritative", all(token in smart_js for token in ["管理岗位分 10 级", "专业技术岗位分 13 级", "工勤技能技术工岗位分 5 级", "本校已生效方案"]))
    check("lifecycle real chromium click-through exists", LIFECYCLE_BROWSER.exists() and "backend_business_transactions_executed" in lifecycle_browser)
    check("lifecycle chromium covers all 14 routes", all(route in lifecycle_browser for route in lifecycle_routes))
    check("permission denied state gives safe authorization next step", "角色和数据范围" in permission_guard and "按职责授权" in permission_guard)

    for code in [f"HR{i:02d}" for i in range(1, 19)]:
        check(f"{code} contextual guide exists", re.search(rf"\b{code}:\s*\{{", js) is not None)

    task_count = len(re.findall(r'^\s*\["[^\n]+",\s*"HR\d{2}",\s*"/hr/', js, flags=re.M))
    check("at least 36 direct business task entries", task_count >= 36)

    prompt_count = len(re.findall(r'prompts:\s*\[', js))
    check("all 18 modules have prompt chips", prompt_count >= 18)
    check("each module gets at least 20 prompt choices with module-specific and generic prompts", prompt_count >= 18 and "MODULE_EXTRA_PROMPTS[moduleCode]" in js and len(re.findall(r'^\s*"[^"\n]+",?$', generic_block, flags=re.M)) >= 16)

    glossary_block = js[js.index("const GLOSSARY = Object.freeze({"):js.index("const MODULE_GLOSSARY")]
    glossary_count = len(re.findall(r'^\s*"[^"]+":\s*"', glossary_block, flags=re.M))
    check("glossary contains at least 24 HR terms", glossary_count >= 24)

    journey_count = len(re.findall(r'id:\s*"[a-z-]+",\n\s*title:', js))
    check("at least 6 cross-module guided routes", journey_count >= 6)

    route_count = len(re.findall(r'route:\s*"/hr/', js)) + task_count
    check("guide contains many direct HR routes", route_count >= 50)

    guide_routes = sorted(set(re.findall(r'"(/hr/[^"?#]+)"', js)))
    route_sources: list[str] = []
    for base in (ROOT / "frontend/templates", ROOT / "backend"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".html", ".js"} or path == JS:
                continue
            try:
                route_sources.append(path.read_text("utf-8"))
            except UnicodeDecodeError:
                continue
    route_corpus = "\n".join(route_sources)
    missing_routes = [route for route in guide_routes if route not in route_corpus and route.rstrip("/") not in route_corpus]
    check("all guide/journey routes resolve to shipped source routes", not missing_routes)

    # No dynamic employee/person data may be read into the AI-ready prompt.
    prompt_fn = js[js.index("function buildSafePrompt"):js.index("function answerFor")]
    forbidden = ["textContent", "innerText", "dataset.staff", "dataset.person", "employeeId", "staffId"]
    for token in forbidden:
        check(f"safe prompt does not read {token}", token not in prompt_fn)

    print(f"HR usability source gate: {len(checks)}/{len(checks)} PASS")
    for name, _ in checks:
        print(f"PASS  {name}")


if __name__ == "__main__":
    main()
