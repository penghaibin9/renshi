"""
hr_structure/api/urls.py

HR02 API 路由（独立前缀 /api/hr/v1/structure/）。
"""

from django.urls import path

from hr_structure.api import views as api_views

urlpatterns = [
    path(
        "api/hr/v1/structure/organizations/bootstrap",
        api_views.organizations_bootstrap,
        name="hr-api-structure-org-bootstrap",
    ),
    path(
        "api/hr/v1/structure/organizations/tree",
        api_views.organizations_tree,
        name="hr-api-structure-org-tree",
    ),
    path(
        "api/hr/v1/structure/organizations/<int:org_id>",
        api_views.organization_detail,
        name="hr-api-structure-org-detail",
    ),
    path(
        "api/hr/v1/structure/organization-changes",
        api_views.organization_changes,
        name="hr-api-structure-org-changes",
    ),
    # 岗位预占（总册 50.1）
    path(
        "api/hr/v1/structure/position-reservations",
        api_views.position_reservations,
        name="hr-api-position-reservations",
    ),
    path(
        "api/hr/v1/structure/position-reservations/<int:reservation_id>/<str:action>",
        api_views.position_reservation_action,
        name="hr-api-position-reservation-action",
    ),
    path(
        "api/hr/v1/structure/position-reservations/list",
        api_views.position_reservations_list,
        name="hr-api-position-reservations-list",
    ),
    path(
        "api/hr/v1/structure/position-control/availability",
        api_views.position_availability,
        name="hr-api-position-availability",
    ),
]
