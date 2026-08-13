from django.urls import path
from . import views

app_name = "hr_appointment"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("policies/", views.workspace, {"section": "policies"}, name="policies"),
    path("quota/", views.workspace, {"section": "quota"}, name="quota"),
    path("competitions/", views.workspace, {"section": "competitions"}, name="competitions"),
    path("applications/", views.workspace, {"section": "applications"}, name="applications"),
    path("ranking/", views.workspace, {"section": "ranking"}, name="ranking"),
    path("publicity/", views.workspace, {"section": "publicity"}, name="publicity"),
    path("appointments/", views.workspace, {"section": "appointments"}, name="appointments"),
    path("term-changes/", views.workspace, {"section": "term_changes"}, name="term_changes"),
    # Compatibility routes retained while callers move to the granular workspaces.
    path("supply/", views.workspace, {"section": "quota"}, name="supply_compat"),
    path("review/", views.workspace, {"section": "ranking"}, name="review_compat"),
    path("terms/", views.workspace, {"section": "appointments"}, name="terms_compat"),
]
