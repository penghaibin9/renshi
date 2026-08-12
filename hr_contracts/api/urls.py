"""HR07 canonical API routes."""

from django.urls import path

from hr_contracts.api import views

app_name = "hr_contracts_api"

urlpatterns = [
    path("api/v1/hr/contracts/dashboard/", views.dashboard, name="hr07-dashboard"),
    path("api/v1/hr/contracts/agreements/", views.agreement_create, name="hr07-agreement-create"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/", views.agreement_detail, name="hr07-agreement-detail"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/sign-initial/", views.sign_initial, name="hr07-sign-initial"),
    path("api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/<uuid:version_id>/activate/", views.activate_initial, name="hr07-activate-initial"),
]
