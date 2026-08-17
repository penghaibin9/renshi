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
    # 党政组织与业务关系（HR02-02）
    path(
        "api/hr/v1/structure/org-relations",
        api_views.org_relations,
        name="hr-api-org-relations",
    ),
    path(
        "api/hr/v1/structure/org-relations/<int:relation_id>/close",
        api_views.org_relation_close,
        name="hr-api-org-relation-close",
    ),
    # 编制方案（HR02-03）
    path(
        "api/hr/v1/structure/staffing-plans",
        api_views.staffing_plans,
        name="hr-api-staffing-plans",
    ),
    path(
        "api/hr/v1/structure/staffing-plans/list",
        api_views.staffing_plans_list,
        name="hr-api-staffing-plans-list",
    ),
    path(
        "api/hr/v1/structure/staffing-plans/<int:plan_id>/<str:action>",
        api_views.staffing_plan_action,
        name="hr-api-staffing-plan-action",
    ),
    # 岗位目录（HR02-04）
    path(
        "api/hr/v1/structure/post-catalogs",
        api_views.post_catalogs,
        name="hr-api-post-catalogs",
    ),
    path(
        "api/hr/v1/structure/post-catalogs/list",
        api_views.post_catalogs_list,
        name="hr-api-post-catalogs-list",
    ),
    path(
        "api/hr/v1/structure/post-grade-schemes",
        api_views.post_grade_schemes,
        name="hr-api-post-grade-schemes",
    ),
    # 组织岗位历史与重组（HR02-06）
    path(
        "api/hr/v1/structure/change-cases",
        api_views.change_cases_list,
        name="hr-api-change-cases",
    ),
    path(
        "api/hr/v1/structure/change-cases/<int:case_id>/<str:action>",
        api_views.change_case_action,
        name="hr-api-change-case-action",
    ),
    path(
        "api/hr/v1/structure/effective-runner/run",
        api_views.effective_runner_trigger,
        name="hr-api-effective-runner",
    ),
    # Legacy 迁移 + Projection + Cutover（S9/S10）
    path(
        "api/hr/v1/structure/projection/run",
        api_views.projection_run,
        name="hr-api-projection-run",
    ),
    path(
        "api/hr/v1/structure/projection/reconcile",
        api_views.projection_reconcile,
        name="hr-api-projection-reconcile",
    ),
    path(
        "api/hr/v1/structure/cutover",
        api_views.cutover,
        name="hr-api-cutover",
    ),
    path(
        "api/hr/v1/structure/cutover/status",
        api_views.cutover_status,
        name="hr-api-cutover-status",
    ),
    # 岗位台账（HR02-05）
    path(
        "api/hr/v1/structure/positions",
        api_views.positions_list,
        name="hr-api-positions",
    ),
    path(
        "api/hr/v1/structure/position-control/summary",
        api_views.position_control_summary,
        name="hr-api-position-control-summary",
    ),
    # 组织 Excel 导入（HR02 23 节）
    path(
        "api/hr/v1/structure/organization-import",
        api_views.organization_import,
        name="hr-api-organization-import",
    ),
]
