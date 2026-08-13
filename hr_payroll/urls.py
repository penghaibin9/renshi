from django.urls import path

from . import views

app_name = "hr_payroll"

urlpatterns = [
    path("", views.workspace, name="overview"),
    path("profiles/", views.workspace, {"section": "profiles"}, name="profiles"),
    path("periods/", views.workspace, {"section": "periods"}, name="periods"),
    path("calculations/", views.workspace, {"section": "calculations"}, name="calculations"),
    path("rules/", views.workspace, {"section": "rules"}, name="rules"),
    path("allowances/", views.workspace, {"section": "allowances"}, name="allowances"),
    path("social-security/", views.workspace, {"section": "social_security"}, name="social_security"),
    path("results/", views.workspace, {"section": "results"}, name="results"),
    path("payments/", views.workspace, {"section": "payments"}, name="payments"),
    path("reconciliation/", views.workspace, {"section": "reconciliation"}, name="reconciliation"),
    path("legacy-takeover/", views.workspace, {"section": "legacy_takeover"}, name="legacy_takeover"),
    # Compatibility entry retained while callers move from the old combined page.
    path("benefits/", views.workspace, {"section": "allowances"}, name="benefits_compat"),
]
