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

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["HR_BROWSER_USERNAME"]
PASSWORD = os.environ["HR_BROWSER_PASSWORD"]
ARTIFACT_DIR = Path(os.getenv("HR_BROWSER_ARTIFACT_DIR", "artifacts/hr-browser-flow"))

# Every journey starts from the rendered HR01 module hub. ``entry_href`` must be
# present as an actual anchor on that page. ``landing_path`` accounts only for
# canonical prefix redirects such as /hr/structure/ -> organizations.
JOURNEYS = [
    ("HR01", "/hr/overview", "/hr/overview", "/hr/todos"),
    ("HR02", "/hr/structure/", "/hr/structure/organizations", "/hr/structure/positions"),
    ("HR03", "/hr/staff/", "/hr/staff/", "/hr/staff/data-quality/"),
    ("HR04", "/hr/recruitment/", "/hr/recruitment/campaigns", "/hr/recruitment/candidates"),
    ("HR05", "/hr/onboarding/", "/hr/onboarding/prehires", "/hr/onboarding/reporting"),
    ("HR06", "/hr/changes/", "/hr/changes/", "/hr/changes/transfers"),
    ("HR07", "/hr/contracts/", "/hr/contracts/", "/hr/contracts/risks/"),
    ("HR08", "/hr/external-teachers/", "/hr/external-teachers/", "/hr/external-teachers/industry/"),
    ("HR09", "/hr/qualifications/", "/hr/qualifications/", "/hr/qualifications/credentials/"),
    ("HR10", "/hr/development/dashboard", "/hr/development/dashboard", "/hr/development/plans"),
    ("HR11", "/hr/time/", "/hr/time/", "/hr/time/attendance/"),
    ("HR12", "/hr/assessments/", "/hr/assessments/", "/hr/assessments/policies/"),
    ("HR13", "/hr/titles/", "/hr/titles/", "/hr/titles/applications/"),
    ("HR14", "/hr/appointments/", "/hr/appointments/", "/hr/appointments/policies/"),
    ("HR15", "/hr/payroll/", "/hr/payroll/", "/hr/payroll/periods/"),
    ("HR16", "/hr/exit/", "/hr/exit/", "/hr/exit/cases/"),
    ("HR17", "/hr/self/", "/hr/self/", "/hr/self/services/"),
    ("HR18", "/hr/data/", "/hr/data/", "/hr/data/quality/"),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _response_status(response) -> int | None:
    return None if response is None else int(response.status)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, object]] = []
    page_errors: list[str] = []
    api_failures: list[str] = []
    console_errors: list[str] = []
    settle_timeouts: list[str] = []
    failure: BaseException | None = None

    def settle(page, label: str) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            # Long polling/notification traffic is allowed. The page/API hard
            # gates below still catch real exceptions and failed HR requests.
            settle_timeouts.append(label)
        page.wait_for_timeout(350)

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
            is_hr_api = "/api/v1/hr/" in response.url or "/api/hr/v1/" in response.url
            if is_hr_api and response.status >= 400:
                api_failures.append(f"{response.status} {response.url}")

        page.on("response", record_api_failure)

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
            require(
                login_result.status < 400,
                f"Login click returned HTTP {login_result.status}",
            )
            settle(page, "login")
            require(
                urlsplit(page.url).path != "/login/",
                "Production login form click returned to /login/",
            )
            session_cookies = [
                cookie for cookie in context.cookies() if cookie["name"] == "sessionid"
            ]
            require(session_cookies, "Production login click did not establish sessionid")
            page.screenshot(
                path=str(ARTIFACT_DIR / "00-login-after-click.png"), full_page=True
            )
            evidence.append(
                {
                    "step": "login",
                    "selector": "button[type=submit]",
                    "http_status": login_result.status,
                    "final_url": page.url,
                    "session_cookie_present": True,
                }
            )

            # Stable hub for all module-entry clicks. Every module is then entered
            # through the anchor users actually see on HR01, not by direct URL.
            hub_response = page.goto(BASE_URL + "/hr/overview", wait_until="domcontentloaded")
            require(hub_response is not None, "HR01 hub returned no response")
            require(hub_response.status == 200, f"HR01 hub HTTP {hub_response.status}")
            settle(page, "hr01-hub")

            for code, entry_href, landing_path, target_path in JOURNEYS:
                # Re-enter the hub between journeys so each module proves its own
                # visible entry point independently.
                if urlsplit(page.url).path != "/hr/overview":
                    hub_response = page.goto(
                        BASE_URL + "/hr/overview", wait_until="domcontentloaded"
                    )
                    require(hub_response is not None, f"{code} hub returned no response")
                    require(hub_response.status == 200, f"{code} hub HTTP {hub_response.status}")
                    settle(page, f"{code}-hub")

                entry_selector = f'a[href="{entry_href}"]'
                entry_link = page.locator(entry_selector).first
                require(
                    entry_link.count() > 0,
                    f"{code} HR01 hub rendered no clickable module entry {entry_href}",
                )
                entry_link.scroll_into_view_if_needed()
                with page.expect_navigation(wait_until="domcontentloaded") as entry_navigation:
                    entry_link.click()
                entry_response = entry_navigation.value
                require(entry_response is not None, f"{code} entry click had no response")
                require(
                    entry_response.status < 400,
                    f"{code} entry click returned HTTP {entry_response.status}",
                )
                settle(page, f"{code}-entry")
                entry_final_path = urlsplit(page.url).path
                evidence.append(
                    {
                        "step": "module-entry-click",
                        "module": code,
                        "selector": entry_selector,
                        "expected_path": landing_path,
                        "final_path": entry_final_path,
                        "http_status": entry_response.status,
                    }
                )
                require(
                    entry_final_path == landing_path,
                    f"{code} entry click redirected to {page.url}",
                )

                target_selector = f'a[href="{target_path}"]'
                target_link = page.locator(target_selector).first
                require(
                    target_link.count() > 0,
                    f"{code} rendered no clickable business link for {target_path}",
                )
                target_link.scroll_into_view_if_needed()
                with page.expect_navigation(wait_until="domcontentloaded") as target_navigation:
                    target_link.click()
                target_response = target_navigation.value
                require(target_response is not None, f"{code} business click had no response")
                require(
                    target_response.status < 400,
                    f"{code} business click returned HTTP {target_response.status}",
                )
                settle(page, f"{code}-business")
                final_path = urlsplit(page.url).path
                evidence.append(
                    {
                        "step": "business-link-click",
                        "module": code,
                        "selector": target_selector,
                        "expected_path": target_path,
                        "final_path": final_path,
                        "http_status": target_response.status,
                    }
                )
                require(final_path == target_path, f"{code} click redirected to {page.url}")
                page.screenshot(
                    path=str(ARTIFACT_DIR / f"{code}-real-runtime-click.png"),
                    full_page=True,
                )

            require(
                not page_errors,
                "Browser page errors: " + " | ".join(page_errors),
            )
            require(
                not api_failures,
                "HR API failures: " + " | ".join(api_failures),
            )
        except BaseException as exc:  # preserve full evidence before failing CI
            failure = exc
            try:
                page.screenshot(
                    path=str(ARTIFACT_DIR / "zz-failure-state.png"), full_page=True
                )
            except Exception:
                pass
        finally:
            try:
                context.tracing.stop(
                    path=str(ARTIFACT_DIR / "real-runtime-click-trace.zip")
                )
            except Exception as exc:
                if failure is None:
                    failure = exc
            try:
                context.close()
            finally:
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
                "networkidle_timeouts": settle_timeouts,
                "failure": None if failure is None else repr(failure),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
