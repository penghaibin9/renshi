"""
hr10_development/urls.py

HR10 页面路由（管理端 UI）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr10_development import views

app_name = "hr10_development"

urlpatterns = [
    path(
        "hr/development/",
        RedirectView.as_view(
            pattern_name="hr10_development:development-dashboard",
            permanent=False,
        ),
        name="development-root",
    ),
    path("hr/development/plans", views.plan_center, name="development-plans"),
    path("hr/development/programs", views.program_center, name="development-programs"),
    path("hr/development/requests", views.request_center, name="development-requests"),
    path("hr/development/enterprise-practice", views.practice_center, name="development-practice"),
    path("hr/development/enterprise-practice/results", views.practice_results, name="development-results"),
    path("hr/development/records/<int:staff_id>", views.development_record, name="development-record"),
    path("hr/development/dashboard", views.development_dashboard, name="development-dashboard"),
]
