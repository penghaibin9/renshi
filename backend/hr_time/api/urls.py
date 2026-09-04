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
    path("api/hr/v1/time/workbench/leave-choices", workbench.leave_choices, name="hr11-leave-choices"),
    path("api/hr/v1/time/calendars/template", workbench.annual_calendar_template, name="hr11-calendar-template"),
    path("api/hr/v1/time/calendars/import", workbench.import_annual_calendar, name="hr11-calendar-import"),
    path("api/hr/v1/time/schedules/create", workbench.create_schedule, name="hr11-schedule-create"),
    path("api/hr/v1/time/leaves/create", workbench.create_leave, name="hr11-leave-create"),
    path("api/hr/v1/time/leaves/<int:leave_id>/evidence", workbench.upload_leave_evidence, name="hr11-leave-evidence-upload"),
    path("api/hr/v1/time/leave-evidence/<int:evidence_id>/download", workbench.download_leave_evidence, name="hr11-leave-evidence-download"),
    path("api/hr/v1/time/leave-accounts/provision", workbench.provision_leave_account, name="hr11-leave-account-provision"),
    path("api/hr/v1/time/exceptions/<int:exception_id>/<str:action>", workbench.exception_action, name="hr11-exception-action"),
    path("api/hr/v1/time/leaves/<int:leave_id>/<str:action>", workbench.leave_action, name="hr11-leave-action"),
    path("api/hr/v1/time/overtime/<int:overtime_id>/<str:action>", workbench.overtime_action, name="hr11-overtime-action"),
    path("api/hr/v1/time/overtime-facts/<int:fact_id>/<str:action>", workbench.overtime_fact_action, name="hr11-overtime-fact-action"),
    path("api/hr/v1/time/close-periods/<int:period_id>/<str:action>", workbench.close_action, name="hr11-close-action"),
    path("api/hr/v1/time/close-periods/create", workbench.create_close_period, name="hr11-close-create"),
    path("api/hr/v1/time/risks/<int:risk_id>/<str:action>", workbench.risk_action, name="hr11-risk-action"),
]
