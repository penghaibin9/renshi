"""HR07 canonical API routes."""

from django.urls import path

from hr_contracts.api import agreements, lifecycle

app_name = "hr_contracts_api"

urlpatterns = [
    path(
        "api/v1/hr/contracts/agreements",
        agreements.agreement_collection,
        name="hr07-agreement-collection",
    ),
    path(
        "api/v1/hr/contracts/agreements/<uuid:agreement_id>",
        agreements.agreement_detail,
        name="hr07-agreement-detail",
    ),
    path(
        "api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/sign",
        agreements.sign_initial_version,
        name="hr07-agreement-sign",
    ),
    path(
        "api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/<uuid:version_id>/activate",
        agreements.activate_initial_version,
        name="hr07-agreement-activate",
    ),
    path(
        "api/v1/hr/contracts/cases",
        lifecycle.case_create,
        name="hr07-case-create",
    ),
    path(
        "api/v1/hr/contracts/cases/<uuid:case_id>/submit",
        lifecycle.case_submit,
        name="hr07-case-submit",
    ),
    path(
        "api/v1/hr/contracts/cases/<uuid:case_id>/approve",
        lifecycle.case_approve,
        name="hr07-case-approve",
    ),
    path(
        "api/v1/hr/contracts/cases/<uuid:case_id>/versions/sign",
        lifecycle.case_sign_successor,
        name="hr07-case-sign-successor",
    ),
    path(
        "api/v1/hr/contracts/cases/<uuid:case_id>/versions/<uuid:version_id>/activate",
        lifecycle.case_activate_successor,
        name="hr07-case-activate-successor",
    ),
    path(
        "api/v1/hr/contracts/cases/<uuid:case_id>/termination/effect",
        lifecycle.case_effect_termination,
        name="hr07-case-effect-termination",
    ),
]
