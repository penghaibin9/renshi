from django.urls import path
from . import views

app_name = "hr_payroll"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("periods/", views.workspace, {"section": "periods"}, name="periods"),
    path("rules/", views.workspace, {"section": "rules"}, name="rules"),
    path("benefits/", views.workspace, {"section": "benefits"}, name="benefits"),
    path("payments/", views.workspace, {"section": "payments"}, name="payments"),
    path("reconciliation/", views.workspace, {"section": "reconciliation"}, name="reconciliation"),
]
