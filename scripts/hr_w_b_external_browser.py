"""W-B multi-role Chromium proof for HR07 agreement confirmation and HR08 activation."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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
    """Issue an API call from the authenticated browser origin, including CSRF."""

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
def authenticated_page(browser: Browser, role: str) -> Iterator[Page]:
    username, password = ROLE_CREDENTIALS[role]
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        login_response = page.goto(
            BASE_URL + "/login/",
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
            login_button.count() == 1,
            f"{role}: expected one visible production login control, "
            f"got {login_button.count()}",
        )
        require(login_button.is_visible(), f"{role}: login control is not visible")
        with page.expect_navigation(wait_until="domcontentloaded") as login_nav:
            login_button.click()
        require(
            login_nav.value is not None and login_nav.value.status < 400,
            f"{role}: login click failed",
        )
        require(
            "/login" not in page.url,
            f"{role}: authentication did not establish a browser session",
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
    api_detail = f"/api/v1/hr/external-teachers/hiring-cases/{case_id}"
    api_options = (
        f"/api/v1/hr/external-teachers/hiring-cases/{case_id}/agreement-options"
    )
    api_agreement = (
        f"/api/v1/hr/external-teachers/hiring-cases/{case_id}/agreement"
    )
    api_activation = (
        f"/api/v1/hr/external-teachers/hiring-cases/{case_id}/activate"
    )

    evidence: list[dict] = []
    failure: BaseException | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                role = "read_only_auditor"
                with authenticated_page(browser, role) as page:
                    response = page.goto(
                        BASE_URL + detail_path,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 200,
                        f"{role}: detail page failed",
                    )
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="WAITING_AGREEMENT"]',
                        timeout=10000,
                    )
                    options = api_request(page, api_options)
                    require(
                        options["status"] == 403,
                        f"{role}: agreement options must be 403, got {options}",
                    )
                    record(evidence, role, "agreement-options-denied", options)
                    confirm = api_request(
                        page,
                        api_agreement,
                        method="POST",
                        body={"agreementId": agreement_id},
                    )
                    require(
                        confirm["status"] == 403,
                        f"{role}: agreement confirmation must be 403, got {confirm}",
                    )
                    record(evidence, role, "agreement-confirm-denied", confirm)
                    activate = api_request(
                        page,
                        api_activation,
                        method="POST",
                        body={},
                    )
                    require(
                        activate["status"] == 403,
                        f"{role}: activation must be 403, got {activate}",
                    )
                    record(evidence, role, "activation-denied", activate)
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "01-read-only-auditor.png"),
                        full_page=True,
                    )

                role = "cross_tenant_operator"
                with authenticated_page(browser, role) as page:
                    own_list = page.goto(
                        BASE_URL + "/hr/external-teachers/hiring/",
                        wait_until="domcontentloaded",
                    )
                    require(
                        own_list is not None and own_list.status == 200,
                        f"{role}: own-tenant workspace failed",
                    )
                    detail = api_request(page, api_detail)
                    require(
                        detail["status"] == 404,
                        f"{role}: cross-tenant detail must be 404, got {detail}",
                    )
                    record(evidence, role, "detail-concealed", detail)
                    options = api_request(page, api_options)
                    require(
                        options["status"] == 404,
                        f"{role}: cross-tenant options must be 404, got {options}",
                    )
                    record(evidence, role, "agreement-options-concealed", options)
                    confirm = api_request(
                        page,
                        api_agreement,
                        method="POST",
                        body={"agreementId": agreement_id},
                    )
                    require(
                        confirm["status"] == 404,
                        f"{role}: cross-tenant confirm must be 404, got {confirm}",
                    )
                    record(evidence, role, "agreement-confirm-concealed", confirm)
                    activate = api_request(
                        page,
                        api_activation,
                        method="POST",
                        body={},
                    )
                    require(
                        activate["status"] == 404,
                        f"{role}: cross-tenant activate must be 404, got {activate}",
                    )
                    record(evidence, role, "activation-concealed", activate)
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
                with authenticated_page(browser, role) as page:
                    response = page.goto(
                        BASE_URL + detail_path,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 200,
                        f"{role}: detail page failed",
                    )
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="WAITING_AGREEMENT"]',
                        timeout=10000,
                    )
                    page.wait_for_selector("[data-agreement-form]", timeout=10000)
                    page.locator(
                        '[data-agreement-form] select[name="agreementId"]'
                    ).select_option(agreement_id)
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "03-approver-before-confirm.png"),
                        full_page=True,
                    )
                    with page.expect_response(
                        lambda api_response: (
                            api_agreement in api_response.url
                            and api_response.request.method == "POST"
                        )
                    ) as response_info:
                        page.locator(
                            '[data-agreement-form] button[type="submit"]'
                        ).click()
                    confirmed_response = response_info.value
                    require(
                        confirmed_response.status == 200,
                        f"{role}: agreement confirm HTTP "
                        f"{confirmed_response.status}",
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
                        {"status": confirmed_response.status},
                    )
                    denied_activation = api_request(
                        page,
                        api_activation,
                        method="POST",
                        body={},
                    )
                    require(
                        denied_activation["status"] == 403,
                        f"{role}: activation must be 403, got {denied_activation}",
                    )
                    record(
                        evidence,
                        role,
                        "activation-denied",
                        denied_activation,
                    )
                    require(
                        page.get_by_role(
                            "button",
                            name="正式激活聘期",
                        ).count()
                        == 0,
                        f"{role}: activation button must not be rendered",
                    )
                    page.screenshot(
                        path=str(ARTIFACT_DIR / "04-approver-ready.png"),
                        full_page=True,
                    )

                role = "activation_operator"
                with authenticated_page(browser, role) as page:
                    response = page.goto(
                        BASE_URL + detail_path,
                        wait_until="domcontentloaded",
                    )
                    require(
                        response is not None and response.status == 200,
                        f"{role}: detail page failed",
                    )
                    page.wait_for_selector(
                        '[data-agreement-workspace]'
                        '[data-case-status="READY_TO_ACTIVATE"]',
                        timeout=10000,
                    )
                    denied_confirm = api_request(
                        page,
                        api_agreement,
                        method="POST",
                        body={"agreementId": agreement_id},
                    )
                    require(
                        denied_confirm["status"] == 403,
                        f"{role}: agreement confirmation must be 403, got "
                        f"{denied_confirm}",
                    )
                    record(
                        evidence,
                        role,
                        "agreement-confirm-denied",
                        denied_confirm,
                    )
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
                        lambda api_response: (
                            api_activation in api_response.url
                            and api_response.request.method == "POST"
                        )
                    ) as response_info:
                        activation_button.click()
                    activated_response = response_info.value
                    require(
                        activated_response.status == 200,
                        f"{role}: activation HTTP {activated_response.status}",
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
                        {"status": activated_response.status},
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
