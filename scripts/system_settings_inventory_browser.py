"""Chromium inventory gate for every visible System Settings entry.

The companion workflow provisions one ordinary school-scoped administrator with
all model permissions inside one CompanyGroupAssignment.  This harness signs in
through the production form, clicks the real top-right gear, discovers the
permission-filtered settings registry rendered in the browser, and clicks every
visible setting entry.  It fails on empty content, browser exceptions, or any
same-origin document/XHR/fetch response at 4xx/5xx.

This is intentionally dynamic: newly registered settings pages automatically
join the browser gate without somebody remembering to update a hard-coded URL
list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.getenv(
    "SETTINGS_INVENTORY_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
USERNAME = os.environ["SETTINGS_INVENTORY_USERNAME"]
PASSWORD = os.environ["SETTINGS_INVENTORY_PASSWORD"]
ARTIFACT_DIR = Path(
    os.getenv(
        "SETTINGS_INVENTORY_ARTIFACT_DIR",
        "tests/artifacts/system-settings-inventory",
    )
)
BUSINESS_PATH = "/hr/external-teachers/hiring/"
SETTINGS_ROOT = "/settings/"

ERROR_TEXT_MARKERS = (
    "Internal Server Error",
    "Server Error (500)",
    "Permission Denied",
    "Page not found",
    "Not Found",
    "Traceback (most recent call last)",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def settle(page, label: str, networkidle_timeouts: list[str]) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightTimeoutError:
        networkidle_timeouts.append(label)
    page.wait_for_timeout(400)


def open_settings_from_real_gear(page) -> None:
    gear = page.locator("#settingsMenu")
    require(gear.count() == 1, "settings gear must be rendered exactly once")
    require(gear.is_visible(), "settings gear is not visible")
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        gear.click()
    response = navigation.value
    require(response is not None, "settings gear produced no navigation response")
    require(response.status < 400, f"settings gear returned HTTP {response.status}")
    require(
        urlsplit(page.url).path.startswith("/settings/"),
        f"settings gear landed outside settings: {page.url}",
    )
    page.locator("#settingsContainer").wait_for(state="visible", timeout=15000)
    page.locator(".accordion-panel a[href]").first.wait_for(
        state="attached",
        timeout=15000,
    )


def discover_menu(page) -> list[dict[str, str]]:
    raw = page.locator(".accordion-panel a[href]").evaluate_all(
        """(links) => links.map((link) => {
          const panel = link.closest('.accordion-panel');
          const groupButton = panel
            ? panel.previousElementSibling
            : null;
          return {
            label: (link.textContent || '').trim().replace(/\s+/g, ' '),
            href: link.getAttribute('href') || '',
            hxGet: link.getAttribute('hx-get') || '',
            group: groupButton
              ? (groupButton.textContent || '').trim().replace(/\s+/g, ' ')
              : ''
          };
        })"""
    )
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        target = (item.get("hxGet") or item.get("href") or "").strip()
        href = (item.get("href") or target).strip()
        if not target.startswith("/"):
            continue
        key = (target, (item.get("label") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            {
                "label": (item.get("label") or target).strip(),
                "group": (item.get("group") or "未分组").strip(),
                "href": href,
                "target": target,
            }
        )
    return unique


def click_inventory_item(
    page,
    item: dict[str, str],
    *,
    unexpected_responses: list[dict[str, object]],
    networkidle_timeouts: list[str],
) -> dict[str, object]:
    target = item["target"]
    target_path = urlsplit(target).path
    selector = f'.accordion-panel a[hx-get="{target}"]'
    link = page.locator(selector).filter(has_text=item["label"]).first
    if link.count() == 0:
        selector = f'.accordion-panel a[href="{item["href"]}"]'
        link = page.locator(selector).filter(has_text=item["label"]).first
    require(
        link.count() == 1,
        f"settings entry cannot be re-located: {item}",
    )

    panel = link.locator("xpath=ancestor::div[contains(@class, 'accordion-panel')]")
    if not link.is_visible():
        toggle = panel.locator("xpath=preceding-sibling::button[1]")
        require(toggle.count() == 1, f"settings group toggle missing: {item}")
        toggle.click()
    link.wait_for(state="visible", timeout=5000)

    before_failure_count = len(unexpected_responses)
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
        response.status < 400,
        f"{item['group']} / {item['label']} returned HTTP {response.status}",
    )
    settle(page, target, networkidle_timeouts)

    container = page.locator("#settingsContainer")
    require(container.count() == 1, f"settings container disappeared after {target}")
    require(container.is_visible(), f"settings container hidden after {target}")
    text = container.inner_text().strip()
    require(text, f"settings page rendered empty content: {target}")
    for marker in ERROR_TEXT_MARKERS:
        require(
            marker not in text,
            f"settings page rendered error marker {marker!r}: {target}",
        )

    new_failures = unexpected_responses[before_failure_count:]
    require(
        not new_failures,
        f"settings page emitted failed subrequests: {target}: {new_failures}",
    )
    return {
        **item,
        "http_status": response.status,
        "content_length": len(text),
        "content_preview": text[:240],
        "final_url": page.url,
    }


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    inventory: list[dict[str, object]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    unexpected_responses: list[dict[str, object]] = []
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

        def record_failed_response(response) -> None:
            if response.status < 400:
                return
            if response.request.resource_type not in {"document", "xhr", "fetch"}:
                return
            parsed = urlsplit(response.url)
            base = urlsplit(BASE_URL)
            if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
                return
            unexpected_responses.append(
                {
                    "status": response.status,
                    "method": response.request.method,
                    "path": parsed.path,
                    "resource_type": response.request.resource_type,
                }
            )

        page.on("response", record_failed_response)
        try:
            login_path = f"/login/?next={quote(BUSINESS_PATH, safe='/')}"
            login_response = page.goto(
                BASE_URL + login_path,
                wait_until="domcontentloaded",
            )
            require(
                login_response is not None and login_response.status == 200,
                "inventory login page failed",
            )
            page.locator("#username").fill(USERNAME)
            page.locator("#password").fill(PASSWORD)
            submit = page.locator("button.yk-login-submit")
            require(
                submit.count() == 1 and submit.is_visible(),
                "visible production login button is missing or ambiguous",
            )
            with page.expect_navigation(wait_until="domcontentloaded") as login_nav:
                submit.click()
            login_result = login_nav.value
            require(
                login_result is not None and login_result.status < 400,
                "inventory login failed",
            )
            require(
                urlsplit(page.url).path == BUSINESS_PATH,
                f"inventory login landed on {page.url}",
            )
            require(
                any(cookie["name"] == "sessionid" for cookie in context.cookies()),
                "inventory login did not establish sessionid",
            )

            open_settings_from_real_gear(page)
            settle(page, "settings-root", networkidle_timeouts)
            menu = discover_menu(page)
            require(
                len(menu) >= 8,
                f"settings registry unexpectedly small: {len(menu)} entries",
            )
            required_targets = {
                "/settings/system-preferences-view/",
                "/settings/company-view/",
            }
            discovered_targets = {item["target"] for item in menu}
            require(
                required_targets <= discovered_targets,
                "required settings pages are missing from the rendered registry: "
                f"{sorted(required_targets - discovered_targets)}",
            )
            (ARTIFACT_DIR / "discovered-menu.json").write_text(
                json.dumps(menu, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "00-settings-registry.png"),
                full_page=True,
            )

            # Ignore no failures: from this point every 4xx/5xx same-origin
            # document/XHR/fetch belongs to a settings click and is fatal.
            unexpected_responses.clear()
            for index, item in enumerate(menu, start=1):
                result = click_inventory_item(
                    page,
                    item,
                    unexpected_responses=unexpected_responses,
                    networkidle_timeouts=networkidle_timeouts,
                )
                result["ordinal"] = index
                inventory.append(result)
                if index in {1, len(menu)} or item["target"] in required_targets:
                    safe_name = "".join(
                        character if character.isalnum() else "-"
                        for character in f"{index:03d}-{item['label']}"
                    ).strip("-")[:90]
                    page.screenshot(
                        path=str(ARTIFACT_DIR / f"{safe_name}.png"),
                        full_page=True,
                    )

            require(not page_errors, f"settings browser page errors: {page_errors}")
            require(
                not unexpected_responses,
                f"settings emitted failed responses: {unexpected_responses}",
            )
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
                "unexpected_responses": unexpected_responses,
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
