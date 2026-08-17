from django.urls import path

from . import views

app_name = "hr_title"

urlpatterns = [
    path("", views.workspace, name="overview"),
    path("applications/", views.workspace, {"section": "applications"}, name="applications"),
    path("eligibility/", views.workspace, {"section": "eligibility"}, name="eligibility"),
    path("materials/", views.workspace, {"section": "materials"}, name="materials"),
    path("experts/", views.workspace, {"section": "experts"}, name="experts"),
    path("deliberation/", views.workspace, {"section": "deliberation"}, name="deliberation"),
    path("publicity/", views.workspace, {"section": "publicity"}, name="publicity"),
    path("appeals/", views.workspace, {"section": "appeals"}, name="appeals"),
    path("results/", views.workspace, {"section": "results"}, name="results"),
    # Compatibility alias retained for the first construction slice.
    path("review/", views.workspace, {"section": "experts"}, name="review"),
]
