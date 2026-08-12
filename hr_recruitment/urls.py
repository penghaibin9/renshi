"""HR04 页面路由（/hr/recruitment/）。"""

from django.urls import path

from hr_recruitment import views

urlpatterns = [
    path("", views.hr04_overview, name="hr04-overview"),
    path("plans", views.hr04_plans, name="hr04-plans"),
    path("campaigns", views.hr04_campaigns, name="hr04-campaigns"),
    path("candidates", views.hr04_candidates, name="hr04-candidates"),
    path("qualification", views.hr04_qualification, name="hr04-qualification"),
    path("assessment", views.hr04_assessment, name="hr04-assessment"),
    path("proposed-hires", views.hr04_proposed_hires, name="hr04-proposed-hires"),
]
