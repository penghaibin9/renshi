"""HR07 canonical API routes."""

from django.urls import path

from hr_contracts.api import agreements

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
]
