"""
hr_recruitment/api/urls.py

HR04 API 路由（统一前缀 /api/hr/v1/recruitment/）。
S1 阶段：健康探针 + envelope 契约自检；S3-S8 逐模块挂载。
"""

from django.urls import path

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
]
