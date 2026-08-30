"""Verify the beginner-facing HR01-HR18 local development structure."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ("01-HR01-人事工作台", "hr_control_center"),
    ("02-HR02-组织机构与编制岗位", "hr_structure"),
    ("03-HR03-教职工主档", "hr_staff"),
    ("04-HR04-招聘与人才引进", "hr_recruitment"),
    ("05-HR05-入职管理", "hr_onboarding"),
    ("06-HR06-人事异动", "hr_changes"),
    ("07-HR07-合同与聘用", "hr_contracts"),
    ("08-HR08-兼职外聘教师", "hr_external"),
    ("09-HR09-教师资格与双师型", "hr_qualification"),
    ("10-HR10-培训进修与企业实践", "hr10_development"),
    ("11-HR11-考勤与请假", "hr_time"),
    ("12-HR12-年度与聘期考核", "hr_assessment"),
    ("13-HR13-职称评审", "hr_title"),
    ("14-HR14-岗位聘任", "hr_appointment"),
    ("15-HR15-薪酬福利", "hr_payroll"),
    ("16-HR16-退休与离校", "hr_exit"),
    ("17-HR17-教职工服务", "hr_self"),
    ("18-HR18-人事数据中心", "hr_data"),
)


def main() -> int:
    errors: list[str] = []
    for hub, app in MODULES:
        if not (ROOT / app).is_dir():
            errors.append(f"missing Django app: {app}")
        if not (ROOT / "modules" / hub / "README.md").is_file():
            errors.append(f"missing module entry: modules/{hub}/README.md")

    workspace_path = ROOT / "Renshi-18模块.code-workspace"
    try:
        workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid workspace: {exc}")
        workspace = {}

    folders = workspace.get("folders", [])
    paths = [row.get("path") for row in folders if isinstance(row, dict)]
    expected_paths = [app for _, app in MODULES]
    if paths != expected_paths:
        errors.append("workspace must expose exactly HR01-HR18 in order")

    if errors:
        print("HR18 structure check: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("HR18 structure check: OK")
    print("- 18 Django apps found")
    print("- 18 beginner module entries found")
    print("- workspace exposes exactly HR01-HR18")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
