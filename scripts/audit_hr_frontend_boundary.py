#!/usr/bin/env python3
"""Database-free audit for canonical HR frontend boundary."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def templates():
    out = list((ROOT / "frontend/templates/hr").rglob("*.html"))
    for app in (ROOT / "backend").glob("hr_*"):
        td = app / "templates"
        if td.exists():
            out.extend(td.rglob("*.html"))
    return sorted(set(out))


def main() -> int:
    paths = templates()
    old_parent = []
    legacy_component = []
    visible_english = []
    parent_counts: dict[str, int] = {}
    old_domains = re.compile(r'(?:href|action)\s*=\s*["\']/(employee|attendance|leave|payroll|pms|project|asset|helpdesk|offboarding|report|dashboard|notifications)(?:/|["\'])')
    old_links = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = str(path.relative_to(ROOT))
        m = re.search(r'{%\s*extends\s+["\']([^"\']+)', text)
        if m:
            parent_counts[m.group(1)] = parent_counts.get(m.group(1), 0) + 1
            if m.group(1) == "index.html":
                old_parent.append(rel)
        for token in ("floating_button.html", "language_settings.html", "profile_section.html", "attendance/components/in_out_component.html"):
            if token in text:
                legacy_component.append({"file": rel, "token": token})
        for hit in old_domains.finditer(text):
            old_links.append({"file": rel, "target": hit.group(0)})
        for no, line in enumerate(text.splitlines(), 1):
            if re.search(r'>\s*[A-Za-z][A-Za-z0-9 /&_-]{2,}\s*<', line) and "Ctrl K" not in line:
                visible_english.append({"file": rel, "line": no, "text": line.strip()[:180]})

    base = (ROOT / "frontend/templates/hr/base.html").read_text(encoding="utf-8")
    header = (ROOT / "frontend/templates/hr/components/header_clean_v16.html").read_text(encoding="utf-8")
    result = {
        "canonical_template_count": len(paths),
        "parent_counts": parent_counts,
        "old_index_parent_count": len(old_parent),
        "old_index_parents": old_parent,
        "legacy_component_reference_count": len(legacy_component),
        "legacy_component_references": legacy_component,
        "hardcoded_old_ui_link_count": len(old_links),
        "hardcoded_old_ui_links": old_links,
        "rough_raw_visible_english_count": len(visible_english),
        "rough_raw_visible_english": visible_english[:50],
        "clean_shell_required": all(x in base + header for x in [
            "hr/components/module_sidebar.html",
            "header_clean_v16.html",
            "hr-shell-clean-v16.css",
            "hr-shell-clean-v16.js",
        ]),
        "pass": not old_parent and not legacy_component and not old_links,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
