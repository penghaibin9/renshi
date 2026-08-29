"""W-B real Chromium proof: confirm HR07 agreement, then activate HR08 engagement."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(os.getenv("HR_BROWSER_ARTIFACT_DIR", "artifacts/hr-w-b-browser"))
SEED_PATH = ARTIFACT_DIR / "seed.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    case_id = seed["case_id"]
    agreement_id = seed["agreement_id"]
    evidence = []
    api_failures = []
    failure = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        def record_api_failure(response) -> None:
            if "/api/v1/hr/" in response.url and response.status >= 400:
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

            detail_url = f"{BASE_URL}/hr/external-teachers/hiring/{case_id}/"
            detail_response = page.goto(detail_url, wait_until="domcontentloaded")
            require(detail_response is not None and detail_response.status == 200, "W-B detail page failed")
            page.wait_for_selector(
                '[data-agreement-workspace][data-case-status="WAITING_AGREEMENT"]',
                timeout=10000,
            )
            page.wait_for_selector('[data-agreement-form]', timeout=10000)
            page.locator('[data-agreement-form] select[name="agreementId"]').select_option(
                agreement_id
            )
            page.screenshot(path=str(ARTIFACT_DIR / "01-waiting-agreement.png"), full_page=True)

            agreement_api = f"/api/v1/hr/external-teachers/hiring-cases/{case_id}/agreement"
            with page.expect_response(
                lambda response: agreement_api in response.url and response.request.method == "POST"
            ) as agreement_response_info:
                page.locator('[data-agreement-form] button[type="submit"]').click()
            agreement_response = agreement_response_info.value
            require(agreement_response.status == 200, f"agreement confirm HTTP {agreement_response.status}")
            page.wait_for_selector(
                '[data-agreement-workspace][data-case-status="READY_TO_ACTIVATE"]',
                timeout=10000,
            )
            evidence.append(
                {
                    "step": "confirm-agreement",
                    "api": agreement_api,
                    "http_status": agreement_response.status,
                    "agreement_id": agreement_id,
                }
            )
            page.screenshot(path=str(ARTIFACT_DIR / "02-ready-to-activate.png"), full_page=True)

            activation_button = page.get_by_role("button", name="正式激活聘期")
            activation_button.wait_for(state="visible", timeout=10000)
            activation_api = f"/api/v1/hr/external-teachers/hiring-cases/{case_id}/activate"
            with page.expect_response(
                lambda response: activation_api in response.url and response.request.method == "POST"
            ) as activation_response_info:
                activation_button.click()
            activation_response = activation_response_info.value
            require(activation_response.status == 200, f"activation HTTP {activation_response.status}")
            page.wait_for_selector(
                '[data-agreement-workspace][data-case-status="ACTIVATED"]',
                timeout=12000,
            )
            evidence.append(
                {
                    "step": "activate-engagement",
                    "api": activation_api,
                    "http_status": activation_response.status,
                }
            )
            page.screenshot(path=str(ARTIFACT_DIR / "03-activated.png"), full_page=True)
            require(not api_failures, "HR API failures: " + " | ".join(api_failures))
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

    (ARTIFACT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps(
            {"api_failures": api_failures, "failure": None if failure is None else repr(failure)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
