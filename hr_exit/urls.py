from django.urls import path
from . import views

app_name = "hr_exit"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("cases/", views.workspace, {"section": "cases"}, name="cases"),
    path("handover/", views.workspace, {"section": "handover"}, name="handover"),
    path("retirement/", views.workspace, {"section": "retirement"}, name="retirement"),
    path("effects/", views.workspace, {"section": "effects"}, name="effects"),
    path("archive/", views.workspace, {"section": "archive"}, name="archive"),
]
