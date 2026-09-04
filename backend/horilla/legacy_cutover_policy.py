"""Frozen deprecation and rollback policy for retired Horilla HR authorities."""

from __future__ import annotations


LEGACY_DEPRECATION_SUNSET = "2026-12-31"
LEGACY_ROLLBACK_MODE = "ENTRY_ADAPTER_ONLY"
LEGACY_FORMAL_WRITER_ROLLBACK_ALLOWED = False
LEGACY_API_SUCCESSOR_ROOT = "/api/v1/hr/"
LEGACY_HR_UI_SUCCESSORS = {
    "dashboard": "/hr/overview",
    "employee": "/hr/staff/",
    "attendance": "/hr/time/attendance/",
    "leave": "/hr/time/leave/",
    "recruitment": "/hr/recruitment/",
    "onboarding": "/hr/onboarding/",
    "pms": "/hr/assessments/",
    "project": "/hr/overview",
    "asset": "/hr/exit/",
    "helpdesk": "/hr/self/",
    "payroll": "/hr/payroll/",
    "offboarding": "/hr/exit/",
    "report": "/hr/data/",
}


def apply_legacy_deprecation_headers(response, *, successor: str = ""):
    """Apply one stable deprecation contract to every legacy entry adapter."""
    response["Deprecation"] = "true"
    response["Sunset"] = LEGACY_DEPRECATION_SUNSET
    if successor:
        response["Link"] = f'<{successor}>; rel="successor-version"'
    return response


def legacy_cutover_policy_snapshot() -> dict:
    """Machine-readable policy used by the global Authority Gate."""
    return {
        "rollbackMode": LEGACY_ROLLBACK_MODE,
        "formalWriterRollbackAllowed": LEGACY_FORMAL_WRITER_ROLLBACK_ALLOWED,
        "sunset": LEGACY_DEPRECATION_SUNSET,
        "apiSuccessorRoot": LEGACY_API_SUCCESSOR_ROOT,
        "uiSuccessors": dict(LEGACY_HR_UI_SUCCESSORS),
    }
