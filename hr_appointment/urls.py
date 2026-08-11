from django.urls import path
from . import views

app_name = "hr_appointment"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("supply/", views.workspace, {"section": "supply"}, name="supply"),
    path("applications/", views.workspace, {"section": "applications"}, name="applications"),
    path("review/", views.workspace, {"section": "review"}, name="review"),
    path("publicity/", views.workspace, {"section": "publicity"}, name="publicity"),
    path("terms/", views.workspace, {"section": "terms"}, name="terms"),
]
