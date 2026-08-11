from django.urls import path
from . import views

app_name = "hr_title"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("applications/", views.workspace, {"section": "applications"}, name="applications"),
    path("materials/", views.workspace, {"section": "materials"}, name="materials"),
    path("review/", views.workspace, {"section": "review"}, name="review"),
    path("publicity/", views.workspace, {"section": "publicity"}, name="publicity"),
    path("results/", views.workspace, {"section": "results"}, name="results"),
]
