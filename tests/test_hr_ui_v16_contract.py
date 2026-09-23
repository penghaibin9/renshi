"""Static production contract for the V16 UI-A integration.

These checks are deliberately database-free: they prove that the uploaded UI menu
labels are wired to the existing V15 routes/templates without importing mock data
or changing Django migrations. MySQL/browser acceptance remains a separate gate.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / "docs/ui_v16/ROUTE_MENU_MATRIX.json").read_text(encoding="utf-8"))
PAGE_MATRIX = json.loads((ROOT / "docs/ui_v16/PAGE_ROUTE_MATRIX.json").read_text(encoding="utf-8"))
SIDEBAR = (ROOT / "frontend/templates/hr/components/module_sidebar.html").read_text(encoding="utf-8")
HR_BASE = (ROOT / "frontend/templates/hr/base.html").read_text(encoding="utf-8")
UI_JS = (ROOT / "frontend/static/hr/js/core/hr-ui-a-v16.js").read_text(encoding="utf-8")


def test_all_18_modules_and_98_declared_menu_entries_are_preserved():
    assert MATRIX["modules"] == 18
    assert MATRIX["declared_menu_entries"] == 98
    assert len(MATRIX["menus"]) == 98
    assert {row["module"] for row in MATRIX["menus"]} == {f"HR{i:02d}" for i in range(1, 19)}


def test_every_ui_menu_target_and_ui_label_is_wired_in_v15_sidebar():
    for row in MATRIX["menus"]:
        target = row["target"]
        if "{{" in target:
            assert "record_url" in SIDEBAR, row
        else:
            assert f'href="{target}"' in SIDEBAR, row
        assert f'<span>{row["ui_label"]}</span>' in SIDEBAR, row



def test_every_design_page_is_accounted_for_against_v15_backend():
    assert len(PAGE_MATRIX) == 138
    statuses = [row["backend_status"] for row in PAGE_MATRIX]
    assert statuses.count("PASS") == 137
    assert statuses.count("STALE_UI_ONLY") == 1
    assert "BLOCKED" not in statuses
    stale = [row for row in PAGE_MATRIX if row["backend_status"] == "STALE_UI_ONLY"]
    assert stale[0]["page_id"] == "R007"
    assert stale[0]["menu_declared"] is False


def test_ui_bridge_is_loaded_by_dedicated_canonical_hr_shell():
    assert "hr-ui-a-v16.css" in HR_BASE
    assert "hr-ui-a-v16.js" in HR_BASE
    assert "hr-shell-v3 hr-ui-a-v16 hr-shell-clean-v16" in HR_BASE
    assert HR_BASE.index("hr-workspace-finish-v6.css") < HR_BASE.index("hr-ui-a-v16.css") < HR_BASE.index("hr-shell-clean-v16.css")
    assert HR_BASE.index("hr-all-menus-polish.js") < HR_BASE.index("hr-ui-a-v16.js") < HR_BASE.index("hr-shell-clean-v16.js")


def test_offline_design_mock_runtime_was_not_copied_into_production():
    # The production bridge indexes the real sidebar. It must not carry the
    # prototype DATA object, fake people, mock state machine or localStorage data.
    forbidden = ["const DATA=", "林知微", "getRows(", "pageState=new Map", "Offline design prototype"]
    for token in forbidden:
        assert token not in UI_JS


def test_v16_adds_no_migration_files():
    # This integration is presentation/menu wiring only; V15 migration graph stays authoritative.
    changed_marker = ROOT / "docs/ui_v16/CHANGED_FILES.txt"
    if changed_marker.exists():
        for line in changed_marker.read_text(encoding="utf-8").splitlines():
            assert "/migrations/" not in line.replace("\\", "/")
