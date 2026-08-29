"""Drive the actually running Django server through real Chromium clicks.

The GitHub Actions workflow boots Django against an ephemeral MySQL service,
then this process signs in through the production form and enters every HR01-
HR18 module by clicking the rendered HR01 business-navigation cards. Modules
that expose explicit local workflows receive real business clicks as well; HR03
uses the technical browser identity seeded by the workflow to traverse the real
roster, profile and person-level workspaces without manufacturing business KPI
or result rows.
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

# code, HR01 hub href, canonical landing path, preferred secondary path,
# secondary path is a hard contract? Consolidated workspace families expose
# explicit local navigation; older standalone shells may still lack one.
JOURNEYS = [
    ("HR01", "/hr/overview", "/hr/overview", "/hr/todos", True),
    ("HR02", "/hr/structure/", "/hr/structure/organizations", "/hr/structure/positions", False),
    ("HR03", "/hr/staff/", "/hr/staff/", "/hr/staff/data-quality/", False),
    ("HR04", "/hr/recruitment/", "/hr/recruitment/campaigns", "/hr/recruitment/candidates", False),
    ("HR05", "/hr/onboarding/", "/hr/onboarding/prehires", "/hr/onboarding/reporting", False),
    ("HR06", "/hr/changes/", "/hr/changes/", "/hr/changes/transfers", False),
    ("HR07", "/hr/contracts/", "/hr/contracts/", "/hr/contracts/risks/", True),
    ("HR08", "/hr/external-teachers/", "/hr/external-teachers/", "/hr/external-teachers/industry/", False),
    ("HR09", "/hr/qualifications/", "/hr/qualifications/", "/hr/qualifications/credentials/", True),
    ("HR10", "/hr/development/dashboard", "/hr/development/dashboard", "/hr/development/plans", False),
    ("HR11", "/hr/time/", "/hr/time/", "/hr/time/attendance/", True),
    ("HR12", "/hr/assessments/", "/hr/assessments/", "/hr/assessments/policies/", True),
    ("HR13", "/hr/titles/", "/hr/titles/", "/hr/titles/applications/", True),
    ("HR14", "/hr/appointments/", "/hr/appointments/", "/hr/appointments/policies/", True),
    ("HR15", "/hr/payroll/", "/hr/payroll/", "/hr/payroll/periods/", True),
    ("HR16", "/hr/exit/", "/hr/exit/", "/hr/exit/cases/", True),
    ("HR17", "/hr/self/", "/hr/self/", "/hr/self/services/", True),
    ("HR18", "/hr/data/", "/hr/data/", "/hr/data/quality/", True),
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
    settle_timeouts: list[str] = []
    failure: BaseException | None = None

    def settle(page, label: str) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            # Notifications/long polling may keep a page busy. A timeout here is
            # diagnostic only; explicit HTTP, pageerror and HR API gates remain.
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
            # Real production login form: fill the browser controls and click the
            # actual submit button. No force_login/test client/session injection.
            login_response = page.goto(BASE_URL + "/login/", wait_until="domcontentloaded")
            require(login_response is not None, "Login page returned no response")
            require(login_response.status == 200, f"Login page HTTP {login_response.status}")
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            with page.expect_navigation(wait_until="domcontentloaded") as login_navigation:
                page.locator("button[type='submit']").click()
            login_result = login_navigation.value
            require(login_result is not None, "Login click produced no navigation response")
            require(login_result.status < 400, f"Login click returned HTTP {login_result.status}")
            settle(page, "login")
            require(
                urlsplit(page.url).path != "/login/",
                "Production login form click returned to /login/",
            )
            session_cookies = [
                cookie for cookie in context.cookies() if cookie["name"] == "sessionid"
            ]
            require(session_cookies, "Production login click did not establish sessionid")
            page.screenshot(path=str(ARTIFACT_DIR / "00-login-after-click.png"), full_page=True)
            evidence.append(
                {
                    "step": "login",
                    "selector": "button[type=submit]",
                    "http_status": login_result.status,
                    "final_url": page.url,
                    "session_cookie_present": True,
                }
            )

            hub_response = page.goto(BASE_URL + "/hr/overview", wait_until="domcontentloaded")
            require(hub_response is not None, "HR01 hub returned no response")
            require(hub_response.status == 200, f"HR01 hub HTTP {hub_response.status}")
            settle(page, "hr01-hub")

            for code, entry_href, landing_path, target_path, require_secondary in JOURNEYS:
                # Start every module journey from the same visible business hub.
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

                if code == "HR03":
                    require(
                        page.locator('[data-module="HR03"][data-section="roster"]').count() == 1,
                        "HR03 roster did not mount the V2 workspace shell",
                    )
                    query_button = page.locator('button:has-text("查询")').first
                    require(query_button.count() > 0, "HR03 rendered no 查询 button")
                    with page.expect_response(
                        lambda response: "/api/hr/v1/staff?" in response.url
                    ) as query_response_info:
                        query_button.click()
                    query_response = query_response_info.value
                    require(
                        query_response.status < 400,
                        f"HR03 查询 click returned HTTP {query_response.status}",
                    )
                    settle(page, "HR03-query")
                    evidence.append(
                        {
                            "step": "business-button-click",
                            "module": code,
                            "selector": 'button:has-text("查询")',
                            "response_url": query_response.url,
                            "http_status": query_response.status,
                        }
                    )

                    # The workflow seeds one technical HrStaffMaster linked to the
                    # browser identity. Use that real row to exercise profile and
                    # all read-only child workspaces; no product KPI/result data is
                    # manufactured merely to make screenshots non-empty.
                    profile_link = page.locator('#rows a[href^="/hr/staff/"]').first
                    require(profile_link.count() > 0, "HR03 roster rendered no real staff profile link")
                    profile_href = profile_link.get_attribute("href")
                    require(
                        bool(profile_href) and profile_href != "/hr/staff/data-quality/",
                        f"HR03 profile link is invalid: {profile_href}",
                    )
                    with page.expect_navigation(wait_until="domcontentloaded") as profile_navigation:
                        profile_link.click()
                    profile_response = profile_navigation.value
                    require(profile_response is not None, "HR03 profile click had no response")
                    require(
                        profile_response.status < 400,
                        f"HR03 profile click returned HTTP {profile_response.status}",
                    )
                    settle(page, "HR03-profile")
                    require(
                        urlsplit(page.url).path == profile_href,
                        f"HR03 profile click redirected to {page.url}",
                    )
                    require(
                        page.locator('[data-module="HR03"][data-section="profile"]').count() == 1,
                        "HR03 profile did not mount the V2 workspace shell",
                    )
                    page.wait_for_function(
                        """() => {
                          const badge = document.getElementById('statusBadge');
                          return badge && !['读取中', ''].includes(badge.textContent.trim());
                        }""",
                        timeout=8000,
                    )
                    evidence.append(
                        {
                            "step": "staff-profile-click",
                            "module": code,
                            "selector": '#rows a[href^="/hr/staff/"]',
                            "expected_path": profile_href,
                            "final_path": urlsplit(page.url).path,
                            "http_status": profile_response.status,
                        }
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "HR03-profile-real-runtime-click.png"),
                        full_page=True,
                    )

                    profile_base = profile_href.rstrip("/")
                    for child_slug, child_section in (
                        ("assignments", "assignments"),
                        ("backgrounds", "backgrounds"),
                        ("materials", "materials"),
                        ("corrections", "corrections"),
                    ):
                        child_path = f"{profile_base}/{child_slug}"
                        child_selector = f'a[href="{child_path}"]'
                        child_link = page.locator(child_selector).first
                        require(
                            child_link.count() > 0,
                            f"HR03 profile rendered no {child_slug} link {child_path}",
                        )
                        with page.expect_navigation(wait_until="domcontentloaded") as child_navigation:
                            child_link.click()
                        child_response = child_navigation.value
                        require(child_response is not None, f"HR03 {child_slug} click had no response")
                        require(
                            child_response.status < 400,
                            f"HR03 {child_slug} click returned HTTP {child_response.status}",
                        )
                        settle(page, f"HR03-{child_slug}")
                        require(
                            urlsplit(page.url).path == child_path,
                            f"HR03 {child_slug} click redirected to {page.url}",
                        )
                        require(
                            page.locator(
                                f'[data-module="HR03"][data-section="{child_section}"]'
                            ).count()
                            == 1,
                            f"HR03 {child_slug} did not mount the V2 workspace shell",
                        )
                        evidence.append(
                            {
                                "step": "staff-child-workspace-click",
                                "module": code,
                                "workspace": child_slug,
                                "selector": child_selector,
                                "expected_path": child_path,
                                "final_path": urlsplit(page.url).path,
                                "http_status": child_response.status,
                            }
                        )
                        page.screenshot(
                            path=str(
                                ARTIFACT_DIR
                                / f"HR03-{child_slug}-real-runtime-click.png"
                            ),
                            full_page=True,
                        )

                        back_selector = f'a[href="{profile_href}"]'
                        back_link = page.locator(back_selector).first
                        require(
                            back_link.count() > 0,
                            f"HR03 {child_slug} rendered no return-to-profile link",
                        )
                        with page.expect_navigation(wait_until="domcontentloaded") as back_navigation:
                            back_link.click()
                        back_response = back_navigation.value
                        require(
                            back_response is not None,
                            f"HR03 {child_slug} return click had no response",
                        )
                        require(
                            back_response.status < 400,
                            f"HR03 {child_slug} return click HTTP {back_response.status}",
                        )
                        settle(page, f"HR03-{child_slug}-return")
                        require(
                            urlsplit(page.url).path == profile_href,
                            f"HR03 {child_slug} return redirected to {page.url}",
                        )

                target_selector = f'a[href="{target_path}"]'
                target_link = page.locator(target_selector).first
                target_count = target_link.count()
                if require_secondary:
                    require(
                        target_count > 0,
                        f"{code} rendered no required business link for {target_path}",
                    )

                if target_count > 0:
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
                            "required": require_secondary,
                        }
                    )
                    require(final_path == target_path, f"{code} click redirected to {page.url}")
                else:
                    evidence.append(
                        {
                            "step": "secondary-link-not-rendered",
                            "module": code,
                            "preferred_path": target_path,
                            "required": False,
                        }
                    )

                page.screenshot(
                    path=str(ARTIFACT_DIR / f"{code}-real-runtime-click.png"),
                    full_page=True,
                )

            require(not page_errors, "Browser page errors: " + " | ".join(page_errors))
            require(not api_failures, "HR API failures: " + " | ".join(api_failures))
        except BaseException as exc:  # preserve full evidence before failing CI
            failure = exc
            try:
                page.screenshot(path=str(ARTIFACT_DIR / "zz-failure-state.png"), full_page=True)
            except Exception:
                pass
        finally:
            try:
                context.tracing.stop(path=str(ARTIFACT_DIR / "real-runtime-click-trace.zip"))
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
