"""Explicit canonical HR routing registry."""

from importlib.util import find_spec

from django.urls import include, path, re_path

from horilla.legacy_hr_api import legacy_hr_api_redirect
from horilla.legacy_hr_ui import legacy_hr_ui_redirect
from hr_external.api import wb_agreement as hr08_wb_agreement_api

urlpatterns = [
    # HR01~HR07 UI routes
    path("hr/", include("hr_control_center.urls")),
    path("hr/structure/", include("hr_structure.urls")),
    path("hr/staff/", include("hr_staff.urls")),
    path("hr/recruitment/", include("hr_recruitment.urls")),
    path("", include("hr_recruitment.public.urls")),
    path("hr/onboarding/", include("hr_onboarding.urls")),
    path("hr/changes/", include("hr_changes.urls")),
    path("hr/contracts/", include("hr_contracts.urls")),
    # HR08 UI
    path("hr/external-teachers/", include("hr_external.urls")),
    # HR09 UI
    path("hr/qualifications/", include("hr_qualification.urls")),
    path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
    # HR10 UI owns its internal /hr/development/... route prefixes.
    path("", include("hr10_development.urls")),
    # HR11 UI
    path("hr/time/", include("hr_time.urls")),
    # HR12 UI
    path("hr/assessments/", include("hr_assessment.urls")),
    # Canonical APIs for old-root modules HR01/02/03/04/05/06/08/11.
    path("", include("horilla.canonical_hr_api")),
    # W-B HR08 agreement confirmation is canonical-only; legacy /api/hr/v1 writes
    # are handled by the global 308 adapter below and land on this same callback.
    path(
        "api/v1/hr/external-teachers/hiring-cases/<uuid:case_id>/agreement-options",
        hr08_wb_agreement_api.hiring_agreement_options,
        name="hr08-api-wb-hiring-agreement-options",
    ),
    path(
        "api/v1/hr/external-teachers/hiring-cases/<uuid:case_id>/agreement",
        hr08_wb_agreement_api.hiring_confirm_agreement,
        name="hr08-api-wb-hiring-agreement",
    ),
    # HR07 canonical Agreement Authority API. Recovery-only legacy handlers stay unrouted.
    path("", include("hr_contracts.api_urls")),
    # HR09/10/12 native canonical APIs.
    path("", include("hr_qualification.api.urls")),
    path("", include("hr10_development.api.urls")),
    path("", include("hr_assessment.api.urls")),
]

# HR13~HR18 are isolated parallel construction lines. Registration remains
# explicit and ordered, while missing sibling apps are not imported on an
# individual child branch. Once branches are recovered together, every present
# Authority is registered by the same table without merge-conflict edits.
PARALLEL_HR_ROUTES = [
    ("hr_title", "hr/titles/", "api/v1/hr/titles/"),  # HR13
    ("hr_appointment", "hr/appointments/", "api/v1/hr/appointments/"),  # HR14
    ("hr_payroll", "hr/payroll/", "api/v1/hr/payroll/"),  # HR15
    ("hr_exit", "hr/exit/", "api/v1/hr/exit/"),  # HR16
    ("hr_self", "hr/self/", "api/v1/hr/self/"),  # HR17
    ("hr_data", "hr/data/", "api/v1/hr/data/"),  # HR18
]

for _app, _ui_prefix, _api_prefix in PARALLEL_HR_ROUTES:
    if find_spec(_app) is None:
        continue
    urlpatterns.extend(
        [
            path(_ui_prefix, include(f"{_app}.urls")),
            path(_api_prefix, include(f"{_app}.api_urls")),
        ]
    )

# Named compatibility aliases keep surviving legacy templates renderable
# without registering the retired payroll URL graph. The adapter preserves
# query strings, sends GET/HEAD to canonical HR15, and rejects legacy writes.
urlpatterns.append(
    path(
        "payroll/view-reimbursement/",
        legacy_hr_ui_redirect,
        {"domain": "payroll", "tail": "view-reimbursement/"},
        name="view-reimbursement",
    )
)

# Retired browser roots remain bookmark-compatible without reviving legacy
# writers. GET/HEAD land on canonical workspaces; unsafe methods fail closed.
for _legacy_domain in ("payroll", "offboarding", "report"):
    urlpatterns.append(
        re_path(
            rf"^{_legacy_domain}(?:/(?P<tail>.*))?$",
            legacy_hr_ui_redirect,
            kwargs={"domain": _legacy_domain},
            name=f"legacy-{_legacy_domain}-ui",
        )
    )

# Legacy API root is adapter-only. 308 preserves POST/PUT/PATCH bodies.
urlpatterns.append(
    re_path(r"^api/hr/v1/(?P<tail>.*)$", legacy_hr_api_redirect, name="legacy-hr-api")
)
