"""W-B multi-role Chromium proof for HR07 agreement and HR08 activation.

Each role signs in through the production form with an explicit ``next`` target.
This prevents narrow HR08 roles from being redirected through the HR01 dashboard,
which they are deliberately not authorised to open.  Every role owns an isolated
browser context; no cookies, superuser privileges, or test-client sessions are
shared.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlsplit

from playwright.sync_api import Browser, Page, sync_playwright


BASE_URL = os.getenv("HR_BROWSER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ARTIFACT_DIR = Path(
    os.getenv("HR_BROWSER_ARTIFACT_DIR", "tests/artifacts/hr-w-b-browser")
)
SEED_PATH = ARTIFACT_DIR / "seed.json"
ROLE_CREDENTIALS = {
    "agreement_approver": (
        os.environ["HR_WB_APPROVER_USERNAME"],
        os.environ["HR_WB_APPROVER_PASSWORD"],
    ),
    "activation_operator": (
        os.environ["HR_WB_ACTIVATOR_USERNAME"],
        os.environ["HR_WB_ACTIVATOR_PASSWORD"],
    ),
    "read_only_auditor": (
        os.environ["HR_WB_AUDITOR_USERNAME"],
        os.environ["HR_WB_AUDITOR_PASSWORD"],
    ),
    "cross_tenant_operator": (
        os.environ["HR_WB_CROSS_TENANT_USERNAME"],
        os.environ["HR_WB_CROSS_TENANT_PASSWORD"],
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def api_request(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
    """Call a canonical HR API from the authenticated browser origin."""

    return page.evaluate(
        """async ({path, method, body}) => {
          const cookie = (name) => document.cookie
            .split(';')
            .map((item) => item.trim())
            .find((item) => item.startsWith(`${name}=`))
            ?.slice(name.length + 1) || '';
          const headers = {'X-Requested-With': 'XMLHttpRequest'};
          if (method !== 'GET') {
            headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
          }
          const options = {method, credentials: 'same-origin', headers};
          if (body !== null) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
          }
          const response = await fetch(path, options);
          const text = await response.text();
          let payload = null;
          try { payload = JSON.parse(text); } catch (_error) {}
          return {status: response.status, payload, text};
        }""",
        {"path": path, "method": method, "body": body},
    )


def record(evidence: list[dict], role: str, assertion: str, result: dict) -> None:
    evidence.append(
        {
            "role": role,
            "assertion": assertion,
            "http_status": result["status"],
            "error_code": (
                ((result.get("payload") or {}).get("error") or {}).get("code")
            ),
        }
    )


@contextmanager
def authenticated_page(
    browser: Browser,
    role: str,
    destination_path: str,
) -> Iterator[Page]:
    """Create one isolated role session and land only in its authorised area."""

    username, password = ROLE_CREDENTIALS[role]
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        login_path = f"/login/?next={quote(destination_path, safe='/')}"
        login_response = page.goto(
            BASE_URL + login_path,
            wait_until="domcontentloaded",
        )
        require(
            login_response is not None and login_response.status == 200,
            f"{role}: login page failed",
        )
        page.locator("#username").fill(username)
        page.locator("#password").fill(password)
        login_button = page.locator("button.yk-login-submit")
        require(
            login_button.count() == 1 and login_button.is_visible(),
            f"{role}: visible production login control is missing or ambiguous",
        )
        with page.expect_navigation(wait_until="domcontentloaded") as login_nav:
            login_button.click()
        login_result = login_nav.value
        require(
            login_result is not None and login_result.status < 400,
            f"{role}: login click failed",
        )
        require(
            urlsplit(page.url).path == destination_path,
            f"{role}: login landed on {page.url}, expected {destination_path}",
        )
        require(
            any(cookie["name"] == "sessionid" for cookie in context.cookies()),
            f"{role}: login did not establish a session cookie",
        )
        yield page
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


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    case_id = seed["case_id"]
    agreement_id = seed["agreement_id"]

    detail_path = f"/hr/external-teachers/hiring/{case_id}/"
    list_path = "/hr/external-teachers/hiring/"
    api_detail = f"/api/v1/hr/external-teachers/hiring-cases/{case_id}"
    api_options = f"{api_detail}/agreement-options"
    api_agreement = f"{api_detail}/agreement"
    api_activation = f"{api_detail}/activate"

    evidence: list[dict] = []
    failure: BaseException | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                role = "read_only_auditor"
                with authenticated_page(browser, role, detail_path) as page:
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="WAITING_AGREEMENT"]',
                        timeout=10000,
                    )
                    for assertion, path, method, body in (
                        ("agreement-options-denied", api_options, "GET", None),
                        (
                            "agreement-confirm-denied",
                            api_agreement,
                            "POST",
                            {"agreementId": agreement_id},
                        ),
                        ("activation-denied", api_activation, "POST", {}),
                    ):
                        result = api_request(page, path, method=method, body=body)
                        require(
                            result["status"] == 403,
                            f"{role}: {assertion} expected 403, got {result}",
                        )
                        record(evidence, role, assertion, result)
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "01-read-only-auditor.png"),
                        full_page=True,
                    )

                role = "cross_tenant_operator"
                with authenticated_page(browser, role, list_path) as page:
                    for assertion, path, method, body in (
                        ("detail-concealed", api_detail, "GET", None),
                        ("agreement-options-concealed", api_options, "GET", None),
                        (
                            "agreement-confirm-concealed",
                            api_agreement,
                            "POST",
                            {"agreementId": agreement_id},
                        ),
                        ("activation-concealed", api_activation, "POST", {}),
                    ):
                        result = api_request(page, path, method=method, body=body)
                        require(
                            result["status"] == 404,
                            f"{role}: {assertion} expected 404, got {result}",
                        )
                        record(evidence, role, assertion, result)
                    html_response = page.goto(
                        BASE_URL + detail_path,
                        wait_until="domcontentloaded",
                    )
                    require(
                        html_response is not None and html_response.status == 404,
                        f"{role}: cross-tenant HTML detail must be 404",
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "02-cross-tenant-concealed.png"),
                        full_page=True,
                    )

                role = "agreement_approver"
                with authenticated_page(browser, role, detail_path) as page:
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="WAITING_AGREEMENT"]',
                        timeout=10000,
                    )
                    form = page.locator("[data-agreement-form]")
                    form.wait_for(state="visible", timeout=10000)
                    form.locator('select[name="agreementId"]').select_option(
                        agreement_id
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "03-approver-before-confirm.png"),
                        full_page=True,
                    )
                    with page.expect_response(
                        lambda response: api_agreement in response.url
                        and response.request.method == "POST"
                    ) as response_info:
                        form.locator('button[type="submit"]').click()
                    confirmed = response_info.value
                    require(
                        confirmed.status == 200,
                        f"{role}: agreement confirmation HTTP {confirmed.status}",
                    )
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="READY_TO_ACTIVATE"]',
                        timeout=12000,
                    )
                    record(
                        evidence,
                        role,
                        "agreement-confirmed",
                        {"status": confirmed.status},
                    )
                    denied = api_request(
                        page,
                        api_activation,
                        method="POST",
                        body={},
                    )
                    require(
                        denied["status"] == 403,
                        f"{role}: activation expected 403, got {denied}",
                    )
                    record(evidence, role, "activation-denied", denied)
                    require(
                        page.get_by_role(
                            "button",
                            name="正式激活聘期",
                        ).count()
                        == 0,
                        f"{role}: activation control must not be rendered",
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "04-approver-ready.png"),
                        full_page=True,
                    )

                role = "activation_operator"
                with authenticated_page(browser, role, detail_path) as page:
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="READY_TO_ACTIVATE"]',
                        timeout=10000,
                    )
                    denied = api_request(
                        page,
                        api_agreement,
                        method="POST",
                        body={"agreementId": agreement_id},
                    )
                    require(
                        denied["status"] == 403,
                        f"{role}: agreement confirmation expected 403, got {denied}",
                    )
                    record(evidence, role, "agreement-confirm-denied", denied)
                    activation_button = page.get_by_role(
                        "button",
                        name="正式激活聘期",
                    )
                    activation_button.wait_for(state="visible", timeout=10000)
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "05-activator-before.png"),
                        full_page=True,
                    )
                    with page.expect_response(
                        lambda response: api_activation in response.url
                        and response.request.method == "POST"
                    ) as response_info:
                        activation_button.click()
                    activated = response_info.value
                    require(
                        activated.status == 200,
                        f"{role}: activation HTTP {activated.status}",
                    )
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="ACTIVATED"]',
                        timeout=12000,
                    )
                    record(
                        evidence,
                        role,
                        "engagement-activated",
                        {"status": activated.status},
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "06-activated.png"),
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
