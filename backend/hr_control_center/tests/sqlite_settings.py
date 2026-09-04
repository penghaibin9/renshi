"""Integrated SQLite settings for the complete HR01 contract suite."""

from pathlib import Path

from hr_onboarding.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_control_center.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR
REPO_ROOT = BASE_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

_extra_apps = (
    "auditlog",
    "hr_control_center",
    "hr_qualification",
    "hr10_development",
    "hr_assessment",
    "hr_title",
    "hr_self",
    "hr_data.apps.HrDataConfig",
)
INSTALLED_APPS = [  # noqa: F405
    *INSTALLED_APPS,
    *(app for app in _extra_apps if app.split(".")[0] not in {row.split(".")[0] for row in INSTALLED_APPS}),
]
MIGRATION_MODULES = {  # noqa: F405
    **MIGRATION_MODULES,
    **{app.split(".")[0]: None for app in _extra_apps},
}
# HR14's suite validates the real deployable migration leaf.
MIGRATION_MODULES.pop("hr_appointment", None)
CANONICAL_HR_APPS = (
    "hr_control_center",
    "hr_structure",
    "hr_staff",
    "hr_recruitment",
    "hr_onboarding",
    "hr_changes",
    "hr_contracts",
    "hr_external",
    "hr_qualification",
    "hr10_development",
    "hr_time",
    "hr_assessment",
    "hr_title",
    "hr_appointment",
    "hr_payroll",
    "hr_exit",
    "hr_self",
    "hr_data",
)

MIDDLEWARE = [  # noqa: F405
    "horilla.horilla_middlewares.ThreadLocalMiddleware",
    *MIDDLEWARE,
    "horilla.legacy_hr_cutover.LegacyWriteAuthorityMiddleware",
]
DATABASE_ROUTERS = ["horilla.legacy_hr_cutover.LegacyWriteAuthorityRouter"]
