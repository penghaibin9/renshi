"""Click every settings page visible to a school-scoped administrator."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("SETTINGS_INVENTORY_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ["SETTINGS_INVENTORY_USERNAME"]
PASSWORD = os.environ["SETTINGS_INVENTORY_PASSWORD"]
ARTIFACT_DIR = Path(
    os.getenv(
        "SETTINGS_INVENTORY_ARTIFACT_DIR",
        "tests/artifacts/system-settings-inventory",
    )
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from horilla.legacy_cutover_policy import LEGACY_HR_UI_SUCCESSORS

BUSINESS_PATH = "/hr/external-teachers/hiring/"
REQUIRED_TARGETS = {
    "/settings/system-preferences-view/",
    "/settings/company-view/",
}
ERROR_MARKERS = (
    "Internal Server Error",
    "Server Error (500)",
    "Permission Denied",
    "Page not found",
    "Traceback (most recent call last)",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def settle(page, label: str, timeouts: list[str]) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightTimeoutError:
        timeouts.append(label)
    page.wait_for_timeout(350)


def settings_link(page):
    """Return the visible real gear link in either supported public shell."""

    links = page.locator('#settingsMenu:visible, a[href="/settings/"]:visible')
    require(links.count() >= 1, "visible /settings/ gear link was not rendered")
    return links.first


def open_settings(page) -> None:
    gear = settings_link(page)
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        gear.click()
    response = navigation.value
    require(
        response is not None and response.status < 400,
        "settings gear navigation failed",
    )
    require(
        urlsplit(page.url).path.startswith("/settings/"),
        f"gear landed on {page.url}",
    )
    page.locator("#settingsContainer").wait_for(state="visible", timeout=15000)
    page.locator(".accordion-panel a[href]").first.wait_for(
        state="attached",
        timeout=15000,
    )


def discover_menu(page) -> list[dict[str, str]]:
    rows = page.locator(".accordion-panel a[href]").evaluate_all(
        r"""links => links.map(link => {
          const panel = link.closest('.accordion-panel');
          const button = panel ? panel.previousElementSibling : null;
          return {
            label: (link.textContent || '').trim().replace(/\s+/g, ' '),
            href: link.getAttribute('href') || '',
            target: link.getAttribute('hx-get') || link.getAttribute('href') || '',
            group: button ? (button.textContent || '').trim().replace(/\s+/g, ' ') : '未分组'
          };
        })"""
    )
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        target = row["target"].strip()
        label = row["label"].strip() or target
        if not target.startswith("/"):
            continue
        key = (target, label)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "label": label,
                "href": row["href"].strip() or target,
                "target": target,
                "group": row["group"].strip() or "未分组",
            }
        )
    return result


def locate_item(page, item: dict[str, str]):
    target = item["target"]
    candidates = page.locator(f'.accordion-panel a[hx-get="{target}"]')
    if candidates.count() == 0:
        candidates = page.locator(f'.accordion-panel a[href="{item["href"]}"]')
    require(candidates.count() >= 1, f"cannot relocate settings item: {item}")
    return candidates.filter(has_text=item["label"]).first


def retired_successor(path):
    """Use the product's frozen retirement map; never guess a redirect target."""
    domain = urlsplit(path).path.strip("/").split("/", 1)[0]
    return LEGACY_HR_UI_SUCCESSORS.get(domain)


def click_item(page, item, failures, timeouts) -> dict[str, object]:
    link = locate_item(page, item)
    require(link.count() == 1, f"ambiguous settings item: {item}")
    panel = link.locator("xpath=ancestor::div[contains(@class, 'accordion-panel')]")
    if not link.is_visible():
        toggle = panel.locator("xpath=preceding-sibling::button[1]")
        require(toggle.count() == 1, f"group toggle missing: {item}")
        toggle.click()
    link.wait_for(state="visible", timeout=5000)

    target_path = urlsplit(item["target"]).path
    successor = retired_successor(item["target"])
    before = len(failures)
    if successor:
        # Both the handoff response and its final document must be observed.
        # Do not count HTTP 308 plus unchanged settings HTML as a passed page.
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15000) as navigation:
            with page.expect_response(
                lambda response: urlsplit(response.url).path == target_path
                and response.request.method == "GET", timeout=15000,
            ) as handoff:
                link.click()
        response = handoff.value
        require(response.status == 204 and response.headers.get("hx-redirect") == successor,
                f"missing explicit workspace handoff: {item}")
        final = navigation.value
        require(final is not None and final.status == 200, f"workspace document failed: {item}")
        actual = urlsplit(page.url)
        origin = urlsplit(BASE_URL)
        expected = urlsplit(successor).path.rstrip("/")
        require((actual.scheme, actual.netloc) == (origin.scheme, origin.netloc)
                and (actual.path.rstrip("/") == expected or actual.path.startswith(expected + "/")),
                f"wrong canonical workspace: {page.url}")
        settle(page, item["target"], timeouts)
        workspace = page.locator("[data-module]")
        require(workspace.count() == 1 and workspace.is_visible(), f"workspace did not mount: {item}")
        text = workspace.inner_text().strip()
        require(text and all(marker not in text for marker in ERROR_MARKERS), f"invalid workspace: {item}")
        require(len(failures) == before, f"failed workspace requests: {failures[before:]}")
        result = {**item, "http_status": final.status, "handoff_status": response.status,
                  "navigation": "retired-workspace-handoff", "content_length": len(text),
                  "content_preview": text[:240], "final_url": page.url,
                  "module": workspace.get_attribute("data-module")}
        # Continue the full inventory through the visible gear, not direct
        # page.goto or a hidden reload that could conceal a broken return path.
        open_settings(page)
        settle(page, "return-from-" + item["target"], timeouts)
        return result
    with page.expect_response(
        lambda response: (
            urlsplit(response.url).path == target_path
            and response.request.method == "GET"
        ),
        timeout=15000,
    ) as response_info:
        link.click()
    response = response_info.value
    require(
        response.status == 200,
        f"{item['group']} / {item['label']} HTTP {response.status}",
    )
    settle(page, item["target"], timeouts)

    container = page.locator("#settingsContainer")
    require(
        container.count() == 1 and container.is_visible(),
        f"container missing: {item}",
    )
    require(urlsplit(page.url).path.rstrip("/") == target_path.rstrip("/"),
            f"settings URL did not change to the requested page: {item}")
    text = container.inner_text().strip()
    require(text, f"empty settings content: {item}")
    for marker in ERROR_MARKERS:
        require(marker not in text, f"error marker {marker!r}: {item}")
    require(
        len(failures) == before,
        f"failed child requests: {failures[before:]}",
    )
    return {
        **item,
        "http_status": response.status,
        "navigation": "settings-fragment",
        "content_length": len(text),
        "content_preview": text[:240],
        "final_url": page.url,
    }


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, object]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict[str, object]] = []
    networkidle_timeouts: list[str] = []
    failure: BaseException | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )

        def observe(response) -> None:
            if response.status < 400 or response.request.resource_type not in {
                "document",
                "xhr",
                "fetch",
            }:
                return
            parsed = urlsplit(response.url)
            origin = urlsplit(BASE_URL)
            if (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc):
                failed_responses.append(
                    {
                        "status": response.status,
                        "method": response.request.method,
                        "path": parsed.path,
                        "resource_type": response.request.resource_type,
                    }
                )

        page.on("response", observe)
        try:
            response = page.goto(
                BASE_URL + f"/login/?next={quote(BUSINESS_PATH, safe='/')}",
                wait_until="domcontentloaded",
            )
            require(
                response is not None and response.status == 200,
                "login page failed",
            )
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            submit = page.locator("button.yk-login-submit")
            require(
                submit.count() == 1 and submit.is_visible(),
                "production login button missing",
            )
            with page.expect_navigation(wait_until="domcontentloaded") as login_info:
                submit.click()
            login = login_info.value
            require(login is not None and login.status < 400, "login failed")
            require(
                urlsplit(page.url).path == BUSINESS_PATH,
                f"login landed on {page.url}",
            )
            require(
                any(cookie["name"] == "sessionid" for cookie in context.cookies()),
                "sessionid missing",
            )

            open_settings(page)
            settle(page, "settings-root", networkidle_timeouts)
            menu = discover_menu(page)
            require(
                len(menu) >= 8,
                f"settings registry unexpectedly small: {len(menu)}",
            )
            targets = {item["target"] for item in menu}
            require(
                REQUIRED_TARGETS <= targets,
                f"required settings missing: {sorted(REQUIRED_TARGETS - targets)}",
            )
            (ARTIFACT_DIR / "discovered-menu.json").write_text(
                json.dumps(menu, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "00-settings-registry.png"),
                full_page=True,
            )

            failed_responses.clear()
            for index, item in enumerate(menu, start=1):
                result = click_item(
                    page,
                    item,
                    failed_responses,
                    networkidle_timeouts,
                )
                result["ordinal"] = index
                inventory.append(result)
                if index in {1, len(menu)} or item["target"] in REQUIRED_TARGETS:
                    page.screenshot(
                        path=str(ARTIFACT_DIR / f"{index:03d}-settings.png"),
                        full_page=True,
                    )

            require(not page_errors, f"page errors: {page_errors}")
            require(not failed_responses, f"failed responses: {failed_responses}")
        except BaseException as exc:
            failure = exc
            try:
                page.screenshot(
                    path=str(ARTIFACT_DIR / "zz-settings-inventory-failure.png"),
                    full_page=True,
                )
            except Exception:
                pass
        finally:
            try:
                context.tracing.stop(
                    path=str(ARTIFACT_DIR / "settings-inventory-trace.zip")
                )
            finally:
                context.close()
                browser.close()

    (ARTIFACT_DIR / "settings-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "diagnostics.json").write_text(
        json.dumps(
            {
                "failure": None if failure is None else repr(failure),
                "visited_count": len(inventory),
                "page_errors": page_errors,
                "console_errors": console_errors,
                "unexpected_responses": failed_responses,
                "networkidle_timeouts": networkidle_timeouts,
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
