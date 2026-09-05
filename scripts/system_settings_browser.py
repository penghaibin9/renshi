"""Three-role Chromium proof for the top-right System Settings workflow."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlsplit

from playwright.sync_api import Browser, Page, sync_playwright

BASE_URL = os.getenv("SETTINGS_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ARTIFACT_DIR = Path(
    os.getenv(
        "SETTINGS_BROWSER_ARTIFACT_DIR",
        "tests/artifacts/system-settings-browser",
    )
)
SEED_PATH = ARTIFACT_DIR / "seed.json"
BUSINESS_PATH = "/hr/external-teachers/hiring/"
SETTINGS_ROOT = "/settings/"
PREFERENCES_PATH = "/settings/system-preferences-view/"
COMPANY_PATH = "/settings/company-view/"
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


def record(evidence, role, assertion, status, detail=None) -> None:
    row = {"role": role, "assertion": assertion, "http_status": status}
    if detail is not None:
        row["detail"] = detail
    evidence.append(row)


def gear_links(page: Page):
    """Recognize the real gear link in both the classic and HR theme shells."""

    return page.locator('#settingsMenu:visible, a[href="/settings/"]:visible')


def api_request(page, path, *, method="GET", body=None, headers=None):
    return page.evaluate(
        """async ({path, method, body, extraHeaders}) => {
          const cookie = name => document.cookie.split(';').map(v => v.trim())
            .find(v => v.startsWith(`${name}=`))?.slice(name.length + 1) || '';
          const requestHeaders = {
            'X-Requested-With': 'XMLHttpRequest',
            ...(extraHeaders || {})
          };
          let encodedBody;
          if (method !== 'GET') {
            requestHeaders['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
            requestHeaders['Content-Type'] = 'application/x-www-form-urlencoded';
            encodedBody = new URLSearchParams(body || {}).toString();
          }
          const response = await fetch(path, {
            method,
            credentials: 'same-origin',
            headers: requestHeaders,
            body: encodedBody
          });
          const text = await response.text();
          let payload = null;
          try { payload = JSON.parse(text); } catch (_error) {}
          return {status: response.status, payload, text};
        }""",
        {
            "path": path,
            "method": method,
            "body": body,
            "extraHeaders": headers,
        },
    )


@contextmanager
def authenticated_page(browser: Browser, role: str) -> Iterator[Page]:
    username, password = ROLE_CREDENTIALS[role]
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        response = page.goto(
            BASE_URL + f"/login/?next={quote(BUSINESS_PATH, safe='/')}",
            wait_until="domcontentloaded",
        )
        require(
            response is not None and response.status == 200,
            f"{role}: login page failed",
        )
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        submit = page.locator("button.yk-login-submit")
        require(
            submit.count() == 1 and submit.is_visible(),
            f"{role}: login button missing",
        )
        with page.expect_navigation(wait_until="domcontentloaded") as info:
            submit.click()
        result = info.value
        require(
            result is not None and result.status < 400,
            f"{role}: login failed",
        )
        require(
            urlsplit(page.url).path == BUSINESS_PATH,
            f"{role}: login landed on {page.url}",
        )
        require(
            any(cookie["name"] == "sessionid" for cookie in context.cookies()),
            f"{role}: session missing",
        )
        yield page
        require(not errors, f"{role}: browser page errors: {errors}")
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


def open_settings(page, role, evidence):
    links = gear_links(page)
    require(links.count() >= 1, f"{role}: visible settings gear missing")
    with page.expect_navigation(wait_until="domcontentloaded") as info:
        links.first.click()
    response = info.value
    require(
        response is not None and response.status == 200,
        f"{role}: gear HTTP failure",
    )
    require(
        urlsplit(page.url).path == PREFERENCES_PATH,
        f"{role}: gear landed on {page.url}",
    )
    page.locator("#settingsContainer").wait_for(state="visible", timeout=15000)
    page.locator("#setting-default-records-per-page").wait_for(
        state="visible",
        timeout=15000,
    )
    record(
        evidence,
        role,
        "top-right-gear-opens-system-preferences",
        200,
        PREFERENCES_PATH,
    )


def save_preferences(
    page,
    role,
    evidence,
    *,
    pagination,
    date_format,
    time_format,
):
    page.locator("#id_pagination").fill(str(pagination))
    with page.expect_response(
        lambda response: (
            "/settings/pagination-settings-view/" in response.url
            and response.request.method == "POST"
        )
    ) as info:
        page.locator('[data-settings-save="pagination"]').click()
    require(info.value.status == 200, f"{role}: pagination HTTP {info.value.status}")
    record(evidence, role, "pagination-saved-from-ui", 200, pagination)

    page.locator("#dateFormat").select_option(date_format)
    with page.expect_response(
        lambda response: (
            "/settings/save-date/" in response.url
            and response.request.method == "POST"
        )
    ) as info:
        page.locator('[data-settings-save="date"]').click()
    require(info.value.status == 200, f"{role}: date HTTP {info.value.status}")
    require(
        info.value.json().get("selected_format") == date_format,
        f"{role}: date response mismatch",
    )
    record(evidence, role, "date-format-saved-from-ui", 200, date_format)

    page.locator("#timeFormat").select_option(time_format)
    with page.expect_response(
        lambda response: (
            "/settings/save-time/" in response.url
            and response.request.method == "POST"
        )
    ) as info:
        page.locator('[data-settings-save="time"]').click()
    require(info.value.status == 200, f"{role}: time HTTP {info.value.status}")
    require(
        info.value.json().get("selected_format") == time_format,
        f"{role}: time response mismatch",
    )
    record(evidence, role, "time-format-saved-from-ui", 200, time_format)

    page.reload(wait_until="domcontentloaded")
    page.locator("#setting-default-records-per-page").wait_for(
        state="visible",
        timeout=15000,
    )
    require(
        page.locator("#id_pagination").input_value() == str(pagination),
        f"{role}: pagination reload mismatch",
    )
    require(
        page.locator("#dateFormat").input_value() == date_format,
        f"{role}: date reload mismatch",
    )
    require(
        page.locator("#timeFormat").input_value() == time_format,
        f"{role}: time reload mismatch",
    )
    record(
        evidence,
        role,
        "preferences-reloaded-from-server",
        200,
        {
            "pagination": pagination,
            "date_format": date_format,
            "time_format": time_format,
        },
    )


def open_company_settings(
    page,
    role,
    evidence,
    *,
    expected,
    forbidden,
    record_evidence=True,
):
    link = page.locator(f'.accordion-panel a[href="{COMPANY_PATH}"]')
    require(link.count() == 1, f"{role}: company settings link missing")
    if not link.is_visible():
        panel = link.locator("xpath=ancestor::div[contains(@class, 'accordion-panel')]")
        panel.locator("xpath=preceding-sibling::button[1]").click()
    link.wait_for(state="visible", timeout=5000)
    with page.expect_response(
        lambda response: (
            COMPANY_PATH in response.url
            and response.request.method == "GET"
        )
    ) as info:
        link.click()
    require(
        info.value.status == 200,
        f"{role}: company settings HTTP {info.value.status}",
    )
    rows = page.locator("#listContainer tr[data-instance-id]")
    rows.first.wait_for(state="visible", timeout=15000)
    text = page.locator("#settingsContainer").inner_text()
    require(expected in text, f"{role}: own school missing")
    require(forbidden not in text, f"{role}: foreign school leaked")
    require(rows.count() == 1, f"{role}: expected one school row, got {rows.count()}")
    if record_evidence:
        record(
            evidence,
            role,
            "company-settings-scoped-to-selected-school",
            200,
            expected,
        )


def edit_school(page, role, *, company_id, name, address, forbidden):
    path = f"/settings/company-update/{company_id}/"
    action = page.locator(f'[hx-get="{path}"]')
    require(
        action.count() == 1 and action.is_visible(),
        f"{role}: school edit action missing",
    )
    with page.expect_response(
        lambda response: path in response.url
        and response.request.method == "GET"
    ) as info:
        action.click()
    require(
        info.value.status == 200,
        f"{role}: edit form HTTP {info.value.status}",
    )
    form = page.locator(f'form[hx-post="{path}"]')
    form.wait_for(state="visible", timeout=10000)
    form.locator('[name="company"]').fill(name)
    form.locator('[name="address"]').fill(address)
    form.locator('[name="city"]').fill("Changsha")
    form.locator('[name="zip"]').fill("410000")
    with page.expect_response(
        lambda response: path in response.url
        and response.request.method == "POST"
    ) as info:
        form.locator('button[type="submit"]').click()
    response = info.value
    require(
        response.status == 200 and response.headers.get("hx-redirect"),
        f"{role}: school save failed",
    )

    loaded = page.goto(BASE_URL + PREFERENCES_PATH, wait_until="domcontentloaded")
    require(
        loaded is not None and loaded.status == 200,
        f"{role}: preferences reload failed",
    )
    open_company_settings(
        page,
        role,
        [],
        expected=name,
        forbidden=forbidden,
        record_evidence=False,
    )
    require(
        address in page.locator("#settingsContainer").inner_text(),
        f"{role}: address reload mismatch",
    )


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    evidence = []
    failure = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                role = "school_a_admin"
                with authenticated_page(browser, role) as page:
                    open_settings(page, role, evidence)
                    save_preferences(
                        page,
                        role,
                        evidence,
                        pagination=37,
                        date_format="YYYY-MM-DD",
                        time_format="HH:mm:ss",
                    )
                    open_company_settings(
                        page,
                        role,
                        evidence,
                        expected=seed["school_a_name"],
                        forbidden=seed["school_b_name"],
                    )
                    edit_school(
                        page,
                        role,
                        company_id=seed["school_a_id"],
                        name=seed["school_a_updated_name"],
                        address=seed["school_a_updated_address"],
                        forbidden=seed["school_b_name"],
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "01-school-a-settings.png"),
                        full_page=True,
                    )

                role = "school_a_teacher"
                with authenticated_page(browser, role) as page:
                    require(
                        gear_links(page).count() == 0,
                        f"{role}: settings gear must not render",
                    )
                    record(evidence, role, "settings-gear-not-rendered", 200)
                    response = page.goto(
                        BASE_URL + SETTINGS_ROOT,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 403,
                        f"{role}: settings root not denied",
                    )
                    record(evidence, role, "settings-root-denied", 403)
                    response = page.goto(
                        BASE_URL + PREFERENCES_PATH,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 403,
                        f"{role}: preferences not denied",
                    )
                    record(evidence, role, "system-preferences-denied", 403)
                    for key, assertion, path, value in (
                        (
                            "pagination",
                            "pagination-write-denied",
                            "/settings/pagination-settings-view/",
                            "99",
                        ),
                        (
                            "selected_format",
                            "date-write-denied",
                            "/settings/save-date/",
                            "MM/DD/YYYY",
                        ),
                        (
                            "selected_format",
                            "time-write-denied",
                            "/settings/save-time/",
                            "hh:mm A",
                        ),
                    ):
                        result = api_request(
                            page,
                            path,
                            method="POST",
                            body={key: value},
                        )
                        require(
                            result["status"] == 403,
                            f"{role}: {assertion} got {result}",
                        )
                        record(evidence, role, assertion, 403)
                    result = api_request(
                        page,
                        "/company-list/",
                        headers={"HX-Request": "true"},
                    )
                    require(
                        result["status"] == 403,
                        f"{role}: company list got {result}",
                    )
                    record(evidence, role, "company-list-denied", 403)

                role = "school_b_admin"
                with authenticated_page(browser, role) as page:
                    open_settings(page, role, evidence)
                    save_preferences(
                        page,
                        role,
                        evidence,
                        pagination=61,
                        date_format="DD/MM/YYYY",
                        time_format="hh:mm A",
                    )
                    response = page.goto(
                        BASE_URL
                        + f"/settings/company-update/{seed['school_a_id']}/",
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 404,
                        f"{role}: primary cross-tenant edit not concealed",
                    )
                    record(
                        evidence,
                        role,
                        "cross-tenant-company-form-concealed",
                        404,
                    )
                    response = page.goto(
                        BASE_URL
                        + f"/company-update-form/{seed['school_a_id']}/",
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 404,
                        f"{role}: legacy cross-tenant edit not concealed",
                    )
                    response = page.goto(
                        BASE_URL + PREFERENCES_PATH,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 200,
                        f"{role}: own preferences failed",
                    )
                    open_company_settings(
                        page,
                        role,
                        evidence,
                        expected=seed["school_b_name"],
                        forbidden=seed["school_a_updated_name"],
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "02-school-b-settings.png"),
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
