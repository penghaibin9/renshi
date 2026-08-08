"""
hr_recruitment/api/urls.py

HR04 API 路由（统一前缀 /api/hr/v1/recruitment/）。
S1 阶段：健康探针 + envelope 契约自检；S3-S8 逐模块挂载。
"""

from django.urls import path

from hr_recruitment.api import plan as plan_api
from hr_recruitment.api import views as api_views

urlpatterns = [
    path(
        "api/hr/v1/recruitment/health",
        api_views.hr04_api_health,
        name="hr04-api-health",
    ),
    path(
        "api/hr/v1/recruitment/contract",
        api_views.hr04_api_contract,
        name="hr04-api-contract",
    ),
    # HR04-01 年度用人计划（总册 8.5）
    path(
        "api/hr/v1/recruitment/plans",
        plan_api.list_plans,
        name="hr04-api-plan-list",
    ),
    path(
        "api/hr/v1/recruitment/plans",
        plan_api.create_plan,
        name="hr04-api-plan-create",
    ),
    path(
        "api/hr/v1/recruitment/plans/<uuid:cycle_id>",
        plan_api.plan_detail,
        name="hr04-api-plan-detail",
    ),
    path(
        "api/hr/v1/recruitment/plans/<uuid:cycle_id>/submit",
        plan_api.plan_submit,
        name="hr04-api-plan-submit",
    ),
    path(
        "api/hr/v1/recruitment/plans/<uuid:cycle_id>/approve",
        plan_api.plan_approve,
        name="hr04-api-plan-approve",
    ),
    path(
        "api/hr/v1/recruitment/plan-requests",
        plan_api.create_plan_request,
        name="hr04-api-plan-request-create",
    ),
    path(
        "api/hr/v1/recruitment/plan-requests/<uuid:request_id>/submit",
        plan_api.plan_request_submit,
        name="hr04-api-plan-request-submit",
    ),
    path(
        "api/hr/v1/recruitment/plan-requests/<uuid:request_id>/return",
        plan_api.plan_request_return,
        name="hr04-api-plan-request-return",
    ),
    path(
        "api/hr/v1/recruitment/plan-requests/<uuid:request_id>/approve",
        plan_api.plan_request_approve,
        name="hr04-api-plan-request-approve",
    ),
]
