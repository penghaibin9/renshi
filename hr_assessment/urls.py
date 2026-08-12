"""HR12 考核管理页面路由。"""
from django.urls import path
from hr_assessment import views

app_name = "hr_assessment"
urlpatterns = [
    path("", views.workspace, {"section": "overview"}, name="hr12-overview"),
    path("policies/", views.workspace, {"section": "policies"}, name="hr12-policies"),
    path("goals/", views.workspace, {"section": "goals"}, name="hr12-goals"),
    path("annual/", views.workspace, {"section": "annual"}, name="hr12-annual"),
    path("term/", views.workspace, {"section": "term"}, name="hr12-term"),
    path("ethics/", views.workspace, {"section": "ethics"}, name="hr12-ethics"),
    path("review/", views.workspace, {"section": "review"}, name="hr12-review"),
    path("archive/", views.workspace, {"section": "archive"}, name="hr12-archive"),
]
