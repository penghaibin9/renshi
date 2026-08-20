"""Drive the actually running Django server through real Chromium clicks.

This script is intended for the focused GitHub Actions browser-acceptance job.
The workflow starts ``manage.py runserver`` against an ephemeral MySQL service,
then this process logs in through the production form and clicks representative
navigation links across HR01-HR18. It deliberately does not use Django's test
client or force_login.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(os.getenv("HR_BROWSER_ARTIFACT_DIR", "artifacts/hr-browser-flow"))

JOURNEYS = [
    ("HR01", "/hr/overview", "/hr/todos"),
    ("HR02", "/hr/structure/organizations", "/hr/structure/positions"),
    ("HR03", "/hr/staff/", "/hr/staff/data-quality/"),
    ("HR04", "/hr/recruitment/campaigns", "/hr/recruitment/candidates"),
    ("HR05", "/hr/onboarding/prehires", "/hr/onboarding/reporting"),
    ("HR06", "/hr/changes/", "/hr/changes/transfers"),
    ("HR07", "/hr/contracts/", "/hr/contracts/risks/"),
    ("HR08", "/hr/external-teachers/", "/hr/external-teachers/industry/"),
    ("HR09", "/hr/qualifications/", "/hr/qualifications/credentials/"),
    ("HR10", "/hr/development/dashboard", "/hr/development/plans"),
    ("HR11", "/hr/time/", "/hr/time/attendance/"),
    ("HR12", "/hr/assessments/", "/hr/assessments/policies/"),
    ("HR13", "/hr/titles/", "/hr/titles/applications/"),
    ("HR14", "/hr/appointments/", "/hr/appointments/policies/"),
    ("HR15", "/hr/payroll/", "/hr/payroll/periods/"),
    ("HR16", "/hr/exit/", "/hr/exit/cases/"),
    ("HR17", "/hr/self/", "/hr/self/services/"),
    ("HR18", "/hr/data/", "/hr/data/quality/"),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, object]] = []
    page_errors: list[str] = []
    api_failures: list[str] = []
    console_errors: list[str] = []

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
            if "/api/v1/hr/" in response.url and response.status >= 400:
                api_failures.append(f"{response.status} {response.url}")

        page.on("response", record_api_failure)

        login_response = page.goto(BASE_URL + "/login/", wait_until="networkidle")
        require(login_response is not None, "Login page returned no response")
        require(login_response.status == 200, f"Login page HTTP {login_response.status}")
        page.locator("#username").fill(USERNAME)
        page.locator("#password").fill(PASSWORD)
        with page.expect_navigation(wait_until="networkidle"):
            page.locator("button[type='submit']").click()
        require(
            urlsplit(page.url).path != "/login/",
            "Production login form click returned to /login/",
        )
        page.screenshot(path=str(ARTIFACT_DIR / "00-login-after-click.png"), full_page=True)
        evidence.append(
            {
                "step": "login",
                "selector": "button[type=submit]",
                "final_url": page.url,
            }
        )

        for code, start_path, target_path in JOURNEYS:
            response = page.goto(BASE_URL + start_path, wait_until="networkidle")
            require(response is not None, f"{code} start returned no response")
            require(
                response.status == 200,
                f"{code} start {start_path} returned HTTP {response.status}",
            )
            require(
                urlsplit(page.url).path == start_path,
                f"{code} start redirected to {page.url}",
            )

            selector = f'a[href="{target_path}"]'
            link = page.locator(selector).first
            require(link.count() > 0, f"{code} rendered no clickable link for {target_path}")
            link.scroll_into_view_if_needed()
            with page.expect_navigation(wait_until="networkidle"):
                link.click()
            final_path = urlsplit(page.url).path
            evidence.append(
                {
                    "step": "module-click",
                    "module": code,
                    "start_path": start_path,
                    "selector": selector,
                    "expected_path": target_path,
                    "final_path": final_path,
                }
            )
            require(final_path == target_path, f"{code} click redirected to {page.url}")
            page.screenshot(
                path=str(ARTIFACT_DIR / f"{code}-real-runtime-click.png"),
                full_page=True,
            )

        context.tracing.stop(path=str(ARTIFACT_DIR / "real-runtime-click-trace.zip"))
        context.close()
        browser.close()

    (ARTIFACT_DIR / "real-runtime-click-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ARTIFACT_DIR / "browser-diagnostics.json").write_text(
        json.dumps(
            {
                "page_errors": page_errors,
                "api_failures": api_failures,
                "console_errors": console_errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    require(not page_errors, "Browser page errors: " + " | ".join(page_errors))
    require(not api_failures, "Canonical HR API failures: " + " | ".join(api_failures))
    # Console errors are recorded as evidence because some third-party/static noise
    # may be non-fatal; page exceptions and application API failures remain hard gates.


if __name__ == "__main__":
    main()
