"""Browser-first acceptance for the W-A HR04 -> HR05 handoff.

The workflow seeds one handoff-ready proposed hire in ephemeral MySQL, signs in
through the production login form, opens the real HR04 proposed-hire page and
clicks the rendered handoff button. A pass requires the canonical production
POST to return 201 with a real HR05 case id; no test client or force_login is used.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(
    os.getenv("HR_WA_BROWSER_ARTIFACT_DIR", "tests/artifacts/hr-w-a-handoff-browser")
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def settle(page, label: str, diagnostics: list[str]) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        diagnostics.append(f"networkidle timeout: {label}")
    page.wait_for_timeout(300)


def response_body(response) -> str:
    """Return a diagnostic response body without masking the original HTTP failure."""
    try:
        return response.text()
    except Exception as exc:  # noqa: BLE001
        return f"<response body unavailable: {exc}>"


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {}
    diagnostics: list[str] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    unexpected_api_failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )

        def record_api_failure(response) -> None:
            path = urlsplit(response.url).path
            if (
                path.startswith("/api/hr/v1/")
                or path.startswith("/api/v1/hr/")
            ) and response.status >= 400:
                unexpected_api_failures.append(f"{response.status} {response.url}")

        page.on("response", record_api_failure)
        failure: BaseException | None = None

        try:
            login_response = page.goto(BASE_URL + "/login/", wait_until="domcontentloaded")
            require(login_response is not None, "Login page returned no response")
            require(login_response.status == 200, f"Login page HTTP {login_response.status}")
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            with page.expect_navigation(wait_until="domcontentloaded") as login_navigation:
                page.locator("button[type='submit']").click()
            login_result = login_navigation.value
            require(login_result is not None, "Login click produced no navigation response")
            require(login_result.status < 400, f"Login click HTTP {login_result.status}")
            settle(page, "login", diagnostics)
            require(urlsplit(page.url).path != "/login/", "Login returned to /login/")
            require(
                any(cookie["name"] == "sessionid" for cookie in context.cookies()),
                "Production login did not establish sessionid",
            )
            evidence["login_status"] = login_result.status

            list_response = page.goto(
                BASE_URL + "/hr/recruitment/proposed-hires",
                wait_until="domcontentloaded",
            )
            require(list_response is not None, "HR04 proposed-hire page returned no response")
            require(list_response.status == 200, f"HR04 proposed-hire page HTTP {list_response.status}")
            settle(page, "proposed-hires", diagnostics)

            row = page.locator("tr", has_text="W-A 张三").first
            row.wait_for(state="visible", timeout=10000)
            button = row.locator("button[data-hr04-handoff]")
            require(button.count() == 1, "Approved W-A proposed hire has no HR05 handoff button")
            proposed_id = button.get_attribute("data-hr04-handoff")
            require(bool(proposed_id), "HR05 handoff button has no proposed-hire id")
            page.screenshot(
                path=str(ARTIFACT_DIR / "01-before-handoff.png"), full_page=True
            )

            canonical_path = (
                f"/api/v1/hr/recruitment/proposed-hires/{proposed_id}/handoff-to-hr05"
            )
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and urlsplit(response.url).path == canonical_path,
                timeout=15000,
            ) as handoff_wait:
                button.click()
            handoff_response = handoff_wait.value
            require(
                handoff_response.status == 201,
                "HR04 -> HR05 canonical handoff HTTP "
                f"{handoff_response.status}: {response_body(handoff_response)}",
            )
            payload = handoff_response.json()
            data = payload.get("data") or {}
            require(data.get("status") == "CREATED", f"Unexpected handoff status: {payload}")
            case_id = data.get("hr05_case_id")
            require(bool(case_id), f"Handoff returned no hr05_case_id: {payload}")

            button.wait_for(state="visible")
            require(
                "已交接 HR05" in button.inner_text(),
                "UI did not enter completed handoff state",
            )
            feedback = row.locator("[data-hr04-handoff-feedback]").inner_text()
            require(str(case_id) in feedback, "UI did not render the real HR05 case id")
            page.screenshot(
                path=str(ARTIFACT_DIR / "02-after-handoff.png"), full_page=True
            )

            evidence.update(
                {
                    "proposed_hire_id": proposed_id,
                    "handoff_http_status": handoff_response.status,
                    "handoff_status": data.get("status"),
                    "hr05_case_id": str(case_id),
                    "final_url": page.url,
                }
            )
        except BaseException as exc:  # noqa: BLE001
            failure = exc
            try:
                page.screenshot(
                    path=str(ARTIFACT_DIR / "failure.png"), full_page=True
                )
            except Exception as screenshot_exc:  # noqa: BLE001
                diagnostics.append(f"failure screenshot error: {screenshot_exc}")
        finally:
            evidence["diagnostics"] = diagnostics
            evidence["page_errors"] = page_errors
            evidence["console_errors"] = console_errors
            evidence["unexpected_api_failures"] = unexpected_api_failures
            (ARTIFACT_DIR / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                context.tracing.stop(path=str(ARTIFACT_DIR / "trace.zip"))
            finally:
                context.close()
                browser.close()

        if failure is not None:
            raise failure
        require(not page_errors, f"Browser page errors: {page_errors}")
        require(not console_errors, f"Browser console errors: {console_errors}")
        require(
            not unexpected_api_failures,
            f"Unexpected HR API failures: {unexpected_api_failures}",
        )


if __name__ == "__main__":
    main()
