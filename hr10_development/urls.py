"""
hr10_development/urls.py

HR10 页面路由（管理端 UI）。
"""

from django.urls import path

from hr10_development import views

app_name = "hr10_development"

urlpatterns = [
    path("hr/development/plans", views.plan_center, name="development-plans"),
    path("hr/development/programs", views.program_center, name="development-programs"),
    path("hr/development/requests", views.request_center, name="development-requests"),
    path("hr/development/enterprise-practice", views.practice_center, name="development-practice"),
    path("hr/development/records/<int:staff_id>", views.development_record, name="development-record"),
    path("hr/development/dashboard", views.development_dashboard, name="development-dashboard"),
]
