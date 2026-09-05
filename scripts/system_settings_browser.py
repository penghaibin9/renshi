"""Real Chromium proof for the top-right System Settings workflow.

Three ordinary, company-scoped users are exercised in isolated browser
contexts:

* School A settings administrator clicks the real top-right gear and persists
  pagination, date and time preferences.
* School A teacher has no gear and all direct settings writes fail closed.
* School B settings administrator persists different values and cannot address
  School A's company form.

The workflow companion performs the final MySQL readback.  This browser harness
never uses ``force_login``, superuser privileges, shared cookies, or direct ORM
writes after the server starts.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlsplit

from playwright.sync_api import Browser, Page, sync_playwright


BASE_URL = os.getenv("SETTINGS_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip(
    "/"
)
ARTIFACT_DIR = Path(
    os.getenv(
        "SETTINGS_BROWSER_ARTIFACT_DIR",
        "tests/artifacts/system-settings-browser",
    )
)
SEED_PATH = ARTIFACT_DIR / "seed.json"
BUSINESS_PATH = "/hr/external-teachers/hiring/"
SETTINGS_ROOT = "/settings/"
SYSTEM_PREFERENCES_PATH = "/settings/system-preferences-view/"

ROLE_CREDENTIALS = {
    "school_a_admin": (
        os.environ["SETTINGS_ADMIN_A_USERNAME"],
        os.environ["SETTINGS_ADMIN_A_PASSWORD"],
    ),
    "school_a_teacher": (
        os.environ["SETTINGS_TEACHER_USERNAME"],
        os.environ["SETTINGS_TEACHER_PASSWORD"],
    ),
    "school_b_admin": (
        os.environ["SETTINGS_ADMIN_B_USERNAME"],
        os.environ["SETTINGS_ADMIN_B_PASSWORD"],
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def record(
    evidence: list[dict],
    *,
    role: str,
    assertion: str,
    status: int | None = None,
    detail: object | None = None,
) -> None:
    row = {"role": role, "assertion": assertion}
    if status is not None:
        row["http_status"] = status
    if detail is not None:
        row["detail"] = detail
    evidence.append(row)


def api_request(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, str] | None = None,
) -> dict:
    """Call a same-origin settings endpoint with the browser's real CSRF token."""

    return page.evaluate(
        """async ({path, method, body}) => {
          const cookie = (name) => document.cookie
            .split(';')
            .map((item) => item.trim())
            .find((item) => item.startsWith(`${name}=`))
            ?.slice(name.length + 1) || '';
          const headers = {'X-Requested-With': 'XMLHttpRequest'};
          let encodedBody = undefined;
          if (method !== 'GET') {
            headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
            encodedBody = new URLSearchParams(body || {}).toString();
          }
          const response = await fetch(path, {
            method,
            credentials: 'same-origin',
            headers,
            body: encodedBody
          });
          const text = await response.text();
          let payload = null;
          try { payload = JSON.parse(text); } catch (_error) {}
          return {status: response.status, payload, text};
        }""",
        {"path": path, "method": method, "body": body},
    )


@contextmanager
def authenticated_page(
    browser: Browser,
    role: str,
    *,
    destination: str = BUSINESS_PATH,
) -> Iterator[Page]:
    username, password = ROLE_CREDENTIALS[role]
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        login_path = f"/login/?next={quote(destination, safe='/')}"
        response = page.goto(BASE_URL + login_path, wait_until="domcontentloaded")
        require(
            response is not None and response.status == 200,
            f"{role}: login page failed",
        )
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        button = page.locator("button.yk-login-submit")
        require(
            button.count() == 1 and button.is_visible(),
            f"{role}: visible production login button is missing or ambiguous",
        )
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.click()
        result = navigation.value
        require(
            result is not None and result.status < 400,
            f"{role}: login HTTP {None if result is None else result.status}",
        )
        require(
            urlsplit(page.url).path == destination,
            f"{role}: login landed on {page.url}, expected {destination}",
        )
        require(
            any(cookie["name"] == "sessionid" for cookie in context.cookies()),
            f"{role}: login did not establish sessionid",
        )
        yield page
        require(not page_errors, f"{role}: browser page errors: {page_errors}")
    except BaseException:
        try:
            page.screenshot(
                path=str(ARTIFACT_DIR / f"zz-{role}-failure.png"),
                full_page=True,
            )
        except Exception:
            pass
        raise
    finally:
        try:
            context.tracing.stop(path=str(ARTIFACT_DIR / f"trace-{role}.zip"))
        finally:
            context.close()


def open_settings_from_gear(page: Page, role: str, evidence: list[dict]) -> None:
    gear = page.locator("#settingsMenu")
    require(gear.count() == 1, f"{role}: top-right settings gear count != 1")
    require(gear.is_visible(), f"{role}: top-right settings gear is not visible")
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        gear.click()
    response = navigation.value
    require(
        response is not None and response.status == 200,
        f"{role}: settings gear HTTP {None if response is None else response.status}",
    )
    require(
        urlsplit(page.url).path == SYSTEM_PREFERENCES_PATH,
        f"{role}: settings gear landed on {page.url}",
    )
    page.locator("#settingsContainer").wait_for(state="visible", timeout=15000)
    page.locator("#setting-default-records-per-page").wait_for(
        state="visible",
        timeout=15000,
    )
    record(
        evidence,
        role=role,
        assertion="top-right-gear-opens-system-preferences",
        status=response.status,
        detail=urlsplit(page.url).path,
    )


def save_preferences(
    page: Page,
    role: str,
    evidence: list[dict],
    *,
    pagination: int,
    date_format: str,
    time_format: str,
) -> None:
    pagination_input = page.locator("#id_pagination")
    require(pagination_input.is_editable(), f"{role}: pagination is not editable")
    pagination_input.fill(str(pagination))
    with page.expect_response(
        lambda response: (
            "/settings/pagination-settings-view/" in response.url
            and response.request.method == "POST"
        )
    ) as pagination_info:
        page.locator('[data-settings-save="pagination"]').click()
    pagination_response = pagination_info.value
    require(
        pagination_response.status == 200,
        f"{role}: pagination save HTTP {pagination_response.status}",
    )
    record(
        evidence,
        role=role,
        assertion="pagination-saved-from-ui",
        status=pagination_response.status,
        detail=pagination,
    )

    page.locator("#dateFormat").select_option(date_format)
    with page.expect_response(
        lambda response: (
            "/settings/save-date/" in response.url
            and response.request.method == "POST"
        )
    ) as date_info:
        page.locator('[data-settings-save="date"]').click()
    date_response = date_info.value
    require(date_response.status == 200, f"{role}: date save HTTP {date_response.status}")
    page.locator('[data-settings-save="date"][data-state="saved"]').wait_for(
        state="attached",
        timeout=10000,
    )
    date_payload = date_response.json()
    require(
        date_payload.get("selected_format") == date_format,
        f"{role}: date response mismatch {date_payload}",
    )
    record(
        evidence,
        role=role,
        assertion="date-format-saved-from-ui",
        status=date_response.status,
        detail=date_format,
    )

    page.locator("#timeFormat").select_option(time_format)
    with page.expect_response(
        lambda response: (
            "/settings/save-time/" in response.url
            and response.request.method == "POST"
        )
    ) as time_info:
        page.locator('[data-settings-save="time"]').click()
    time_response = time_info.value
    require(time_response.status == 200, f"{role}: time save HTTP {time_response.status}")
    page.locator('[data-settings-save="time"][data-state="saved"]').wait_for(
        state="attached",
        timeout=10000,
    )
    time_payload = time_response.json()
    require(
        time_payload.get("selected_format") == time_format,
        f"{role}: time response mismatch {time_payload}",
    )
    record(
        evidence,
        role=role,
        assertion="time-format-saved-from-ui",
        status=time_response.status,
        detail=time_format,
    )

    page.reload(wait_until="domcontentloaded")
    page.locator("#setting-default-records-per-page").wait_for(
        state="visible",
        timeout=15000,
    )
    require(
        page.locator("#id_pagination").input_value() == str(pagination),
        f"{role}: pagination did not survive reload",
    )
    require(
        page.locator("#dateFormat").input_value() == date_format,
        f"{role}: date format did not survive reload",
    )
    require(
        page.locator("#timeFormat").input_value() == time_format,
        f"{role}: time format did not survive reload",
    )
    record(
        evidence,
        role=role,
        assertion="preferences-reloaded-from-server",
        status=200,
        detail={
            "pagination": pagination,
            "date_format": date_format,
            "time_format": time_format,
        },
    )


def click_company_settings(
    page: Page,
    role: str,
    evidence: list[dict],
    *,
    expected_company: str,
    forbidden_company: str,
) -> None:
    link = page.locator('.accordion-panel a[href="/settings/company-view/"]')
    require(link.count() == 1, f"{role}: company settings link is missing")
    panel = link.locator("xpath=ancestor::div[contains(@class, 'accordion-panel')]")
    if not link.is_visible():
        panel.locator("xpath=preceding-sibling::button[1]").click()
    link.wait_for(state="visible", timeout=5000)
    with page.expect_response(
        lambda response: (
            "/settings/company-view/" in response.url
            and response.request.method == "GET"
        )
    ) as response_info:
        link.click()
    response = response_info.value
    require(response.status == 200, f"{role}: company settings HTTP {response.status}")
    page.wait_for_timeout(700)
    container_text = page.locator("#settingsContainer").inner_text()
    require(
        expected_company in container_text,
        f"{role}: selected school is missing from company settings",
    )
    require(
        forbidden_company not in container_text,
        f"{role}: other tenant leaked into company settings",
    )
    record(
        evidence,
        role=role,
        assertion="company-settings-scoped-to-selected-school",
        status=response.status,
        detail=expected_company,
    )


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    evidence: list[dict] = []
    failure: BaseException | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                role = "school_a_admin"
                with authenticated_page(browser, role) as page:
                    open_settings_from_gear(page, role, evidence)
                    save_preferences(
                        page,
                        role,
                        evidence,
                        pagination=37,
                        date_format="YYYY-MM-DD",
                        time_format="HH:mm:ss",
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "01-school-a-preferences.png"),
                        full_page=True,
                    )
                    click_company_settings(
                        page,
                        role,
                        evidence,
                        expected_company=seed["school_a_name"],
                        forbidden_company=seed["school_b_name"],
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "02-school-a-company.png"),
                        full_page=True,
                    )

                role = "school_a_teacher"
                with authenticated_page(browser, role) as page:
                    require(
                        page.locator("#settingsMenu").count() == 0,
                        f"{role}: settings gear must not be rendered",
                    )
                    record(
                        evidence,
                        role=role,
                        assertion="settings-gear-not-rendered",
                        status=200,
                    )
                    direct = page.goto(
                        BASE_URL + SETTINGS_ROOT,
                        wait_until="domcontentloaded",
                    )
                    require(
                        direct is not None and direct.status == 403,
                        f"{role}: direct settings root expected 403",
                    )
                    record(
                        evidence,
                        role=role,
                        assertion="settings-root-denied",
                        status=direct.status,
                    )
                    preferences = page.goto(
                        BASE_URL + SYSTEM_PREFERENCES_PATH,
                        wait_until="domcontentloaded",
                    )
                    require(
                        preferences is not None and preferences.status == 403,
                        f"{role}: direct preferences expected 403",
                    )
                    record(
                        evidence,
                        role=role,
                        assertion="system-preferences-denied",
                        status=preferences.status,
                    )
                    for assertion, path, value in (
                        ("pagination-write-denied", "/settings/pagination-settings-view/", "99"),
                        ("date-write-denied", "/settings/save-date/", "MM/DD/YYYY"),
                        ("time-write-denied", "/settings/save-time/", "hh:mm A"),
                    ):
                        key = "pagination" if "pagination" in assertion else "selected_format"
                        result = api_request(
                            page,
                            path,
                            method="POST",
                            body={key: value},
                        )
                        require(
                            result["status"] == 403,
                            f"{role}: {assertion} expected 403, got {result}",
                        )
                        record(
                            evidence,
                            role=role,
                            assertion=assertion,
                            status=result["status"],
                        )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "03-teacher-denied.png"),
                        full_page=True,
                    )

                role = "school_b_admin"
                with authenticated_page(browser, role) as page:
                    open_settings_from_gear(page, role, evidence)
                    save_preferences(
                        page,
                        role,
                        evidence,
                        pagination=61,
                        date_format="DD/MM/YYYY",
                        time_format="hh:mm A",
                    )
                    cross_tenant = page.goto(
                        BASE_URL
                        + f"/settings/company-update/{seed['school_a_id']}/",
                        wait_until="domcontentloaded",
                    )
                    require(
                        cross_tenant is not None and cross_tenant.status == 404,
                        f"{role}: cross-tenant company form expected 404",
                    )
                    record(
                        evidence,
                        role=role,
                        assertion="cross-tenant-company-form-concealed",
                        status=cross_tenant.status,
                    )
                    own_preferences = page.goto(
                        BASE_URL + SYSTEM_PREFERENCES_PATH,
                        wait_until="domcontentloaded",
                    )
                    require(
                        own_preferences is not None and own_preferences.status == 200,
                        f"{role}: own preferences failed after concealment check",
                    )
                    click_company_settings(
                        page,
                        role,
                        evidence,
                        expected_company=seed["school_b_name"],
                        forbidden_company=seed["school_a_name"],
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "04-school-b-company.png"),
                        full_page=True,
                    )
            finally:
                browser.close()
    except BaseException as exc:
        failure = exc

    (ARTIFACT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps(
            {
                "failure": None if failure is None else repr(failure),
                "completed_assertions": len(evidence),
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
