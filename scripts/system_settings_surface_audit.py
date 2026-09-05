"""Deep real-browser audit for every reachable system-settings surface.

The positive entry path is always discovered through the rendered top-right
user menu.  After that click, the script crawls same-origin settings navigation,
records desktop and mobile evidence, and fails on broken routes, server errors,
unhandled JavaScript errors, failed settings APIs, placeholder settings links,
duplicate DOM ids, or unusable horizontal overflow.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import TimeoutError, sync_playwright

from system_settings_browser import (
    BASE_URL,
    SETTINGS_NAV_TEXT,
    authenticated_page,
    click_top_right_settings,
    is_error_page,
    require,
    settle,
)


ARTIFACT_DIR = Path(
    os.getenv(
        "SETTINGS_SURFACE_ARTIFACT_DIR",
        "tests/artifacts/system-settings-surface",
    )
)
ADMIN_USERNAME = os.environ["SETTINGS_ADMIN_USERNAME"]
ADMIN_PASSWORD = os.environ["SETTINGS_ADMIN_PASSWORD"]
MAX_PAGES = int(os.getenv("SETTINGS_SURFACE_MAX_PAGES", "80"))

SKIP_PATH = re.compile(
    r"/(?:logout|signout|delete|remove|destroy|reset|clear|purge|download|export|"
    r"impersonate|switch-company|switch-tenant)(?:/|$)",
    re.IGNORECASE,
)
SETTINGS_PATH = re.compile(
    r"setting|configuration|preference|company|organization|permission|role|"
    r"mail|notification|theme|language|locale|timezone|audit|security|general|"
    r"system|tenant|school|brand",
    re.IGNORECASE,
)
PLACEHOLDER_HREF = re.compile(r"^(?:\s*|#|javascript:)", re.IGNORECASE)
DANGEROUS_TEXT = re.compile(
    r"删除|清空|重置|停用|注销|退出|切换租户|delete|remove|clear|reset|"
    r"disable|logout|switch\s*(?:tenant|company)",
    re.IGNORECASE,
)


def canonical_url(raw: str, *, base: str) -> str | None:
    if not raw or PLACEHOLDER_HREF.search(raw):
        return None
    absolute = urljoin(base, raw)
    parsed = urlsplit(absolute)
    base_parsed = urlsplit(BASE_URL)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != base_parsed.netloc:
        return None
    if SKIP_PATH.search(parsed.path):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def route_is_settings_related(url: str, *, settings_home: str, text: str = "") -> bool:
    parsed = urlsplit(url)
    home = urlsplit(settings_home)
    home_parts = [part for part in home.path.split("/") if part]
    shared_root = home_parts[0] if home_parts else ""
    return bool(
        SETTINGS_PATH.search(parsed.path)
        or SETTINGS_NAV_TEXT.search(text)
        or (shared_root and parsed.path.startswith(f"/{shared_root}/"))
        or parsed.path == home.path
    )


def page_links(page, *, settings_home: str) -> list[dict]:
    links = page.locator(
        "main a:visible, [role='main'] a:visible, .oh-main-content a:visible, "
        "aside a:visible, nav a:visible"
    )
    rows: list[dict] = []
    seen: set[str] = set()
    for index in range(min(links.count(), 700)):
        link = links.nth(index)
        try:
            meta = link.evaluate(
                """element => ({
                  text: (element.innerText || element.textContent || '').trim(),
                  href: element.getAttribute('href') || '',
                  title: element.getAttribute('title') || '',
                  aria: element.getAttribute('aria-label') || '',
                  target: element.getAttribute('target') || ''
                })"""
            )
        except Exception:
            continue
        text = " ".join(
            str(meta.get(key, "")) for key in ("text", "title", "aria")
        ).strip()
        if DANGEROUS_TEXT.search(text):
            continue
        url = canonical_url(str(meta.get("href", "")), base=page.url)
        if not url or not route_is_settings_related(
            url,
            settings_home=settings_home,
            text=text,
        ):
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "url": url,
                "href": str(meta.get("href", "")),
                "text": text,
                "target": str(meta.get("target", "")),
                "sourceIndex": index,
            }
        )
    return rows


def placeholder_settings_links(page) -> list[dict]:
    links = page.locator("a:visible")
    rows: list[dict] = []
    for index in range(min(links.count(), 700)):
        link = links.nth(index)
        try:
            meta = link.evaluate(
                """element => ({
                  text: (element.innerText || element.textContent || '').trim(),
                  href: element.getAttribute('href') || '',
                  title: element.getAttribute('title') || '',
                  aria: element.getAttribute('aria-label') || ''
                })"""
            )
        except Exception:
            continue
        text = " ".join(
            str(meta.get(key, "")) for key in ("text", "title", "aria")
        )
        if SETTINGS_NAV_TEXT.search(text) and PLACEHOLDER_HREF.search(
            str(meta.get("href", ""))
        ):
            rows.append({"index": index, **meta})
    return rows


def duplicate_ids(page) -> list[dict]:
    return page.evaluate(
        """() => {
          const counts = new Map();
          document.querySelectorAll('[id]').forEach((element) => {
            const id = element.id;
            if (!id) return;
            counts.set(id, (counts.get(id) || 0) + 1);
          });
          return [...counts.entries()]
            .filter(([, count]) => count > 1)
            .map(([id, count]) => ({id, count}));
        }"""
    )


def layout_metrics(page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.documentElement;
          const body = document.body;
          const main = document.querySelector('main, [role="main"], .oh-main-content');
          const viewportWidth = window.innerWidth;
          const scrollWidth = Math.max(root.scrollWidth, body?.scrollWidth || 0);
          const mainRect = main?.getBoundingClientRect() || null;
          return {
            viewportWidth,
            scrollWidth,
            horizontalOverflow: Math.max(0, scrollWidth - viewportWidth),
            mainVisible: Boolean(mainRect && mainRect.width > 0 && mainRect.height > 0),
            bodyTextLength: (body?.innerText || '').trim().length
          };
        }"""
    )


def audit_current_page(page, *, index: int, viewport_name: str) -> dict:
    metrics = layout_metrics(page)
    placeholders = placeholder_settings_links(page)
    duplicates = duplicate_ids(page)
    row = {
        "index": index,
        "viewport": viewport_name,
        "url": page.url,
        "title": page.title(),
        "metrics": metrics,
        "placeholderSettingsLinks": placeholders,
        "duplicateIds": duplicates,
        "visibleForms": page.locator("form:visible").count(),
        "visibleSubmitControls": page.locator(
            "form button[type='submit']:visible, form input[type='submit']:visible"
        ).count(),
    }
    require(not is_error_page(page), f"settings error page: {page.url}")
    require(metrics["bodyTextLength"] > 0, f"settings page is blank: {page.url}")
    require(metrics["mainVisible"], f"settings main content is not visible: {page.url}")
    require(
        metrics["horizontalOverflow"] <= (24 if viewport_name == "mobile" else 8),
        f"settings {viewport_name} horizontal overflow "
        f"{metrics['horizontalOverflow']}px: {page.url}",
    )
    require(
        not placeholders,
        f"settings page contains placeholder settings links: {page.url} {placeholders}",
    )
    require(
        not duplicates,
        f"settings page contains duplicate DOM ids: {page.url} {duplicates}",
    )
    return row


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    evidence: dict = {
        "entry": {},
        "desktop": [],
        "mobile": [],
        "pageErrors": [],
        "consoleErrors": [],
        "failedResponses": [],
        "failure": None,
    }
    failure: BaseException | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                with authenticated_page(
                    browser,
                    username=ADMIN_USERNAME,
                    password=ADMIN_PASSWORD,
                    next_path="/hr/overview",
                    role="settings-surface-admin",
                ) as page:
                    page.on(
                        "pageerror",
                        lambda exc: evidence["pageErrors"].append(
                            {"url": page.url, "error": str(exc)}
                        ),
                    )
                    page.on(
                        "console",
                        lambda msg: evidence["consoleErrors"].append(
                            {"url": page.url, "text": msg.text}
                        )
                        if msg.type == "error"
                        else None,
                    )

                    def record_failed_response(response) -> None:
                        parsed = urlsplit(response.url)
                        if parsed.netloc != urlsplit(BASE_URL).netloc:
                            return
                        if response.status >= 500 or (
                            response.status >= 400
                            and SETTINGS_PATH.search(parsed.path)
                        ):
                            evidence["failedResponses"].append(
                                {
                                    "url": response.url,
                                    "status": response.status,
                                    "method": response.request.method,
                                    "pageUrl": page.url,
                                }
                            )

                    page.on("response", record_failed_response)
                    settings_url, entry_meta, diagnostics = click_top_right_settings(page)
                    settings_home = settings_url
                    evidence["entry"] = {
                        "settingsUrl": settings_url,
                        "metadata": entry_meta,
                        "diagnostics": diagnostics,
                    }

                    queue: deque[str] = deque([settings_home])
                    queued = {settings_home}
                    visited: set[str] = set()
                    desktop_urls: list[str] = []
                    while queue and len(visited) < MAX_PAGES:
                        url = queue.popleft()
                        if url in visited:
                            continue
                        response = page.goto(url, wait_until="domcontentloaded")
                        require(response is not None, f"settings route had no response: {url}")
                        require(
                            response.status < 400,
                            f"settings route HTTP {response.status}: {url}",
                        )
                        settle(page)
                        final_url = canonical_url(page.url, base=BASE_URL)
                        require(final_url is not None, f"settings route left application: {page.url}")
                        visited.add(url)
                        desktop_urls.append(final_url)
                        row = audit_current_page(
                            page,
                            index=len(evidence["desktop"]),
                            viewport_name="desktop",
                        )
                        links = page_links(page, settings_home=settings_home)
                        row["discoveredLinks"] = links
                        evidence["desktop"].append(row)
                        page.screenshot(
                            path=str(
                                ARTIFACT_DIR
                                / f"desktop-{len(evidence['desktop']):03d}.png"
                            ),
                            full_page=True,
                        )
                        for link in links:
                            if link["url"] not in visited and link["url"] not in queued:
                                queued.add(link["url"])
                                queue.append(link["url"])

                    require(
                        evidence["desktop"],
                        "top-right settings entry exposed no auditable page",
                    )
                    require(
                        not queue,
                        f"settings crawl exceeded MAX_PAGES={MAX_PAGES}; "
                        "navigation may be cyclic or unexpectedly broad",
                    )

                    page.set_viewport_size({"width": 390, "height": 844})
                    unique_mobile_urls = list(dict.fromkeys(desktop_urls))
                    for index, url in enumerate(unique_mobile_urls, start=1):
                        response = page.goto(url, wait_until="domcontentloaded")
                        require(
                            response is not None and response.status < 400,
                            f"mobile settings route failed: {url}",
                        )
                        settle(page)
                        evidence["mobile"].append(
                            audit_current_page(
                                page,
                                index=index,
                                viewport_name="mobile",
                            )
                        )
                        page.screenshot(
                            path=str(ARTIFACT_DIR / f"mobile-{index:03d}.png"),
                            full_page=True,
                        )

                    require(
                        not evidence["pageErrors"],
                        f"settings page errors: {evidence['pageErrors']}",
                    )
                    require(
                        not evidence["failedResponses"],
                        f"settings failed responses: {evidence['failedResponses']}",
                    )
            finally:
                browser.close()
    except BaseException as exc:
        failure = exc
        evidence["failure"] = repr(exc)

    (ARTIFACT_DIR / "surface-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
