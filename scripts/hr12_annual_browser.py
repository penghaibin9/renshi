"""HR12 Annual real Chromium proof: freeze evidence, then finalize one formal result."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(os.getenv("HR_BROWSER_ARTIFACT_DIR", "artifacts/hr12-annual-browser"))
SEED_PATH = ARTIFACT_DIR / "seed.json"
WORKSPACES = (
    ("overview", "/hr/assessments/"),
    ("policies", "/hr/assessments/policies/"),
    ("goals", "/hr/assessments/goals/"),
    ("annual", "/hr/assessments/annual/"),
    ("term", "/hr/assessments/term/"),
    ("ethics", "/hr/assessments/ethics/"),
    ("review", "/hr/assessments/review/"),
    ("archive", "/hr/assessments/archive/"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    case_id = seed["case_id"]
    evidence = []
    api_failures = []
    failure = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        def record_api_failure(response) -> None:
            if "/api/v1/hr/assessments/" in response.url and response.status >= 400:
                api_failures.append(f"{response.status} {response.url}")

        page.on("response", record_api_failure)
        try:
            login_response = page.goto(BASE_URL + "/login/", wait_until="domcontentloaded")
            require(login_response is not None and login_response.status == 200, "login page failed")
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            with page.expect_navigation(wait_until="domcontentloaded") as login_nav:
                page.locator("button[type='submit']").click()
            require(login_nav.value is not None and login_nav.value.status < 400, "login click failed")

            for viewport_name, viewport in (
                ("desktop", {"width": 1440, "height": 1000}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page.set_viewport_size(viewport)
                for workspace_name, workspace_path in WORKSPACES:
                    response = page.goto(BASE_URL + workspace_path, wait_until="domcontentloaded")
                    require(
                        response is not None and response.status == 200,
                        f"HR12 {workspace_name} {viewport_name} page failed",
                    )
                    page.locator("#workRows .hr12-row, #workRows .hr12-empty").first.wait_for(
                        state="visible",
                        timeout=15000,
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / f"workspace-{viewport_name}-{workspace_name}.png"),
                        full_page=True,
                    )
                evidence.append({
                    "step": f"audit-{viewport_name}-workspaces",
                    "pages": len(WORKSPACES),
                    "http_status": 200,
                })

            page.set_viewport_size({"width": 1440, "height": 1000})
            policy_response = page.goto(BASE_URL + "/hr/assessments/policies/", wait_until="domcontentloaded")
            require(policy_response is not None and policy_response.status == 200, "HR12 policies page failed")
            page.locator("[data-open]").click()
            page.locator("#hr12-policy-code").fill("HR12-BROWSER-GOVERNANCE")
            page.locator("#hr12-policy-name").fill("HR12 浏览器制度治理")
            with page.expect_response(
                lambda response: response.url.endswith("/api/v1/hr/assessments/policies")
                and response.request.method == "POST"
            ) as create_info:
                page.locator("[data-form] [type='submit']").click()
            require(create_info.value.status == 201, f"policy create HTTP {create_info.value.status}")
            page.wait_for_timeout(900)
            created_row = page.locator(".hr12-action-row").filter(has_text="HR12-BROWSER-GOVERNANCE")
            created_row.wait_for(state="visible", timeout=15000)
            created_row.locator("[data-rename]").click()
            created_row.locator("[data-rename-form] input[name='name']").fill("HR12 浏览器制度治理（修订）")
            with page.expect_response(
                lambda response: "/api/v1/hr/assessments/policies/" in response.url
                and response.request.method == "PUT"
            ) as rename_info:
                created_row.locator("[data-rename-form] [type='submit']").click()
            require(rename_info.value.status == 200, f"policy rename HTTP {rename_info.value.status}")
            evidence.append({"step": "create-and-rename-policy-pack", "http_status": 200})

            annual_response = page.goto(BASE_URL + "/hr/assessments/annual/", wait_until="domcontentloaded")
            require(annual_response is not None and annual_response.status == 200, "HR12 annual page failed")
            row = page.locator(f'[data-annual-case="{case_id}"]')
            row.wait_for(state="visible", timeout=15000)
            row.locator("[data-annual-snapshot]").wait_for(state="visible", timeout=10000)
            page.screenshot(path=str(ARTIFACT_DIR / "01-annual-proposed.png"), full_page=True)

            snapshot_api = f"/api/v1/hr/assessments/cases/{case_id}/provider-snapshot"
            with page.expect_response(
                lambda response: snapshot_api in response.url and response.request.method == "POST"
            ) as snapshot_info:
                row.locator("[data-annual-snapshot]").click()
            snapshot_response = snapshot_info.value
            require(snapshot_response.status == 200, f"provider snapshot HTTP {snapshot_response.status}")
            row = page.locator(f'[data-annual-case="{case_id}"]')
            row.locator("[data-annual-finalize]").wait_for(state="visible", timeout=15000)
            evidence.append({"step": "freeze-provider-snapshot", "api": snapshot_api, "http_status": 200})
            page.screenshot(path=str(ARTIFACT_DIR / "02-evidence-ready.png"), full_page=True)

            row.locator("[data-annual-grade]").select_option("QUALIFIED")
            finalize_api = f"/api/v1/hr/assessments/cases/{case_id}/finalize"
            with page.expect_response(
                lambda response: finalize_api in response.url and response.request.method == "POST"
            ) as finalize_info:
                row.locator("[data-annual-finalize]").click()
            finalize_response = finalize_info.value
            require(finalize_response.status == 200, f"finalization HTTP {finalize_response.status}")
            final_row = page.locator(f'[data-annual-case="{case_id}"][data-case-status="FINALIZED"]')
            final_row.wait_for(state="visible", timeout=15000)
            require("合格" in final_row.inner_text(), "formal grade not rendered after finalization")
            evidence.append({"step": "finalize-annual-result", "api": finalize_api, "http_status": 200})
            page.screenshot(path=str(ARTIFACT_DIR / "03-finalized.png"), full_page=True)
            require(not api_failures, "HR12 API failures: " + " | ".join(api_failures))
        except BaseException as exc:
            failure = exc
            try:
                page.screenshot(path=str(ARTIFACT_DIR / "zz-failure.png"), full_page=True)
            except Exception:
                pass
        finally:
            try:
                context.tracing.stop(path=str(ARTIFACT_DIR / "trace.zip"))
            finally:
                context.close()
                browser.close()

    (ARTIFACT_DIR / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps({"api_failures": api_failures, "failure": None if failure is None else repr(failure)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
