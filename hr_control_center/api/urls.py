"""
hr_control_center/api/urls.py

HR01 API 路由 —— 独立前缀 /api/hr/v1/home/（不在 /hr/ 页面前缀下）。

总册 31 节：所有 HR01 API 统一前缀 /api/hr/v1/home/。
"""

from django.urls import path

from hr_control_center.api import views as api_views

urlpatterns = [
    path(
        "api/hr/v1/home/bootstrap",
        api_views.home_bootstrap,
        name="hr-api-home-bootstrap",
    ),
    path(
        "api/hr/v1/home/overview/metrics",
        api_views.home_metrics,
        name="hr-api-home-overview-metrics",
    ),
    # 队伍结构（HR01-04）
    path(
        "api/hr/v1/home/workforce/summary",
        api_views.workforce_summary,
        name="hr-api-workforce-summary",
    ),
    path(
        "api/hr/v1/home/workforce/distribution",
        api_views.workforce_distribution,
        name="hr-api-workforce-distribution",
    ),
    path(
        "api/hr/v1/home/workforce/org-comparison",
        api_views.workforce_org_comparison,
        name="hr-api-workforce-org-comparison",
    ),
    # 人事预警（HR01-03）
    path(
        "api/hr/v1/home/alerts",
        api_views.alert_list,
        name="hr-api-alert-list",
    ),
    path(
        "api/hr/v1/home/alerts/summary",
        api_views.alert_summary,
        name="hr-api-alert-summary",
    ),
    path(
        "api/hr/v1/home/alerts/run-rules",
        api_views.alert_run_rules,
        name="hr-api-alert-run-rules",
    ),
]
