"""
hr_time/api/urls.py

HR11 API 路由 —— 旧声明前缀由 canonical registry 映射到 /api/v1/hr/time/。
业务端点复用 S2-S9 Authority 服务，不回退 legacy writer。
"""

from django.urls import path

from hr_time.api import views as api_views
from hr_time.api import workbench

urlpatterns = [
    path(
        "api/hr/v1/time/health",
        api_views.time_health,
        name="hr11-api-time-health",
    ),
    path("api/hr/v1/time/workbench/choices", workbench.choices, name="hr11-workbench-choices"),
    path("api/hr/v1/time/schedules/create", workbench.create_schedule, name="hr11-schedule-create"),
    path("api/hr/v1/time/exceptions/<int:exception_id>/<str:action>", workbench.exception_action, name="hr11-exception-action"),
    path("api/hr/v1/time/leaves/<int:leave_id>/<str:action>", workbench.leave_action, name="hr11-leave-action"),
    path("api/hr/v1/time/overtime/<int:overtime_id>/<str:action>", workbench.overtime_action, name="hr11-overtime-action"),
    path("api/hr/v1/time/overtime-facts/<int:fact_id>/<str:action>", workbench.overtime_fact_action, name="hr11-overtime-fact-action"),
    path("api/hr/v1/time/close-periods/<int:period_id>/<str:action>", workbench.close_action, name="hr11-close-action"),
    path("api/hr/v1/time/risks/<int:risk_id>/<str:action>", workbench.risk_action, name="hr11-risk-action"),
]
