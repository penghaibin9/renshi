"""HR11 考勤时间管理页面路由。"""
from django.urls import path
from hr_time import views

app_name = "hr_time"
urlpatterns = [
    path("", views.workspace, {"section": "overview"}, name="hr11-overview"),
    path("attendance/", views.workspace, {"section": "attendance"}, name="hr11-attendance"),
    path("schedule/", views.workspace, {"section": "schedule"}, name="hr11-schedule"),
    path("leave/", views.workspace, {"section": "leave"}, name="hr11-leave"),
    path("overtime/", views.workspace, {"section": "overtime"}, name="hr11-overtime"),
    path("close/", views.workspace, {"section": "close"}, name="hr11-close"),
    path("risks/", views.workspace, {"section": "risks"}, name="hr11-risks"),
]
