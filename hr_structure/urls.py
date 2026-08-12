"""HR02 页面路由。"""

from django.urls import path

from hr_structure import views

urlpatterns = [
    path("", views.workspace, {"section": "overview"}, name="hr-structure-overview"),
    path("organizations", views.hr_organizations, name="hr-structure-organizations"),
    path("relations", views.workspace, {"section": "relations"}, name="hr-structure-relations"),
    path("staffing-plans", views.workspace, {"section": "staffing"}, name="hr-structure-staffing-plans"),
    path("post-catalogs", views.workspace, {"section": "catalogs"}, name="hr-structure-post-catalogs"),
    path("positions", views.hr_positions, name="hr-structure-positions"),
    path("history", views.workspace, {"section": "history"}, name="hr-structure-history"),
]
