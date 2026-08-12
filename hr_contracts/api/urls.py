"""HR07 canonical API routes."""

from django.urls import path

from hr_contracts.api import lifecycle, views

app_name = "hr_contracts_api"

urlpatterns = [
    path("api/v1/hr/contracts/dashboard/", views.dashboard, name="hr07-dashboard"),
    path("api/v1/hr/contracts/agreements/", views.agreement_create, name="hr07-agreement-create"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/", views.agreement_detail, name="hr07-agreement-detail"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/sign-initial/", views.sign_initial, name="hr07-sign-initial"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/<uuid:version_id>/activate/", views.activate_initial, name="hr07-activate-initial"),
    path("api/v1/hr/contracts/cases/", lifecycle.case_create, name="hr07-case-create"),
    path("api/v1/hr/contracts/cases/<uuid:case_id>/submit/", lifecycle.case_submit, name="hr07-case-submit"),
    path("api/v1/hr/contracts/cases/<uuid:case_id>/approve/", lifecycle.case_approve, name="hr07-case-approve"),
    path("api/v1/hr/contracts/cases/<uuid:case_id>/sign-successor/", lifecycle.case_sign_successor, name="hr07-case-sign-successor"),
    path("api/v1/hr/contracts/cases/<uuid:case_id>/versions/<uuid:version_id>/activate/", lifecycle.case_activate_successor, name="hr07-case-activate-successor"),
    path("api/v1/hr/contracts/cases/<uuid:case_id>/terminate/effect/", lifecycle.case_effect_termination, name="hr07-case-effect-termination"),
]
