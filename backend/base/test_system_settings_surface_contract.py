"""Static contracts for the production system-settings surface.

The real Chromium gate proves runtime behaviour.  These inexpensive checks
provide an earlier failure when a shared header turns the settings entry into a
placeholder or URL configuration loses every concrete settings route.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver


SETTINGS_LABEL = re.compile(
    r"系统设置|平台设置|基础设置|全局设置|system\s*settings?|settings?",
    re.IGNORECASE,
)
CONCRETE_LINK = re.compile(
    r"href\s*=\s*[\"'](?!\s*(?:#|javascript:|$))[^\"']+[\"']"
    r"|href\s*=\s*[\"']\s*\{%\s*url\s+[^%]+%\}\s*[\"']",
    re.IGNORECASE,
)
PLACEHOLDER_LINK = re.compile(
    r"href\s*=\s*[\"']\s*(?:#|javascript:[^\"']*|)\s*[\"']",
    re.IGNORECASE,
)
HEADER_HINT = re.compile(
    r"navbar|topbar|header|profile|user[-_ ]?menu|dropdown|avatar|右上角",
    re.IGNORECASE,
)


def _url_inventory() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def walk(patterns, prefix: str = "") -> None:
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if isinstance(entry, URLPattern):
                rows.append(
                    {
                        "route": route,
                        "name": str(entry.name or ""),
                        "lookup": str(entry.lookup_str or ""),
                    }
                )
            elif isinstance(entry, URLResolver):
                walk(entry.url_patterns, route)

    walk(get_resolver().url_patterns)
    return rows


def _candidate_source_files() -> tuple[Path, ...]:
    roots = {
        Path(settings.BASE_DIR),
        Path(settings.BASE_DIR).parent / "frontend",
    }
    matches: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for suffix in ("*.html", "*.js", "*.vue"):
            matches.extend(root.rglob(suffix))
    return tuple(sorted(set(matches)))


class SystemSettingsSurfaceContractTests(SimpleTestCase):
    maxDiff = None

    def test_urlconf_exposes_at_least_one_concrete_settings_route(self):
        routes = _url_inventory()
        settings_routes = [
            row
            for row in routes
            if SETTINGS_LABEL.search(
                " ".join((row["route"], row["name"], row["lookup"]))
            )
            and "login" not in row["route"].lower()
            and "logout" not in row["route"].lower()
        ]
        self.assertTrue(
            settings_routes,
            "URLConf contains no concrete system/settings route for the "
            "top-right entry",
        )
        self.assertTrue(
            any("<" not in row["route"] for row in settings_routes),
            "Every settings route requires unresolved path parameters; the "
            "top-right menu needs a concrete landing page",
        )

    def test_rendered_source_does_not_define_settings_as_a_placeholder(self):
        labelled_sources: list[dict[str, object]] = []
        concrete_header_entries: list[dict[str, object]] = []
        placeholder_entries: list[dict[str, object]] = []

        for path in _candidate_source_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for match in SETTINGS_LABEL.finditer(text):
                start = max(0, match.start() - 900)
                end = min(len(text), match.end() + 900)
                snippet = text[start:end]
                row = {
                    "path": path.relative_to(Path(settings.BASE_DIR).parent).as_posix(),
                    "label": match.group(0),
                    "snippet": snippet,
                }
                labelled_sources.append(row)
                if PLACEHOLDER_LINK.search(snippet):
                    placeholder_entries.append(row)
                if CONCRETE_LINK.search(snippet) and (
                    HEADER_HINT.search(path.as_posix())
                    or HEADER_HINT.search(snippet)
                ):
                    concrete_header_entries.append(row)

        self.assertTrue(
            labelled_sources,
            "No source file renders a visible system/settings label",
        )
        self.assertTrue(
            concrete_header_entries,
            "No header/user-menu source renders system settings with a "
            "concrete href or Django URL tag",
        )

        # A repository may legitimately contain a separate '#' control near the
        # words 'settings' (for example a dropdown trigger).  Fail only when all
        # labelled candidates are placeholders and none is concrete.
        self.assertFalse(
            placeholder_entries and not concrete_header_entries,
            "All detected system-settings entries are placeholder links",
        )
