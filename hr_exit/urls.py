from django.urls import path
from . import views

app_name = "hr_exit"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("cases/", views.workspace, {"section": "cases"}, name="cases"),
    path("handover/", views.workspace, {"section": "handover"}, name="handover"),
    path("settlement/", views.workspace, {"section": "settlement"}, name="settlement"),
    path("retirement-precheck/", views.workspace, {"section": "retirement_precheck"}, name="retirement_precheck"),
    path("retirement-facts/", views.workspace, {"section": "retirement_facts"}, name="retirement_facts"),
    path("effects/", views.workspace, {"section": "effects"}, name="effects"),
    path("archive/", views.workspace, {"section": "archive"}, name="archive"),
    # Compatibility: historical retirement entry now resolves to formal facts.
    path("retirement/", views.workspace, {"section": "retirement_facts"}, name="retirement_compat"),
]
