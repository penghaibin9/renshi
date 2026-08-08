"""
hr_time/api/urls.py

HR11 API 路由 —— 独立前缀 /api/hr/v1/time/（总册 §131-138 逐步挂载）。
S1 仅提供 health 探针；业务端点随 S2-S9 按阶段挂载。
"""

from django.urls import path

from hr_time.api import views as api_views

urlpatterns = [
    path(
        "api/hr/v1/time/health",
        api_views.time_health,
        name="hr11-api-time-health",
    ),
]
