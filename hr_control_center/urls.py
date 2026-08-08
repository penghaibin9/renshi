"""
hr_control_center/urls.py

页面路由（挂载在 /hr/ 下）：
  /hr/            → 重定向到 overview
  /hr/overview    → HR01-01 人事总览
  /hr/todos       → HR01-02 我的待办
  /hr/alerts      → HR01-03 人事预警
  /hr/workforce   → HR01-04 队伍结构
  /hr/actions     → HR01-05 快捷办理（S7，暂重定向到 overview）

API 路由见 hr_control_center/api/urls.py（独立前缀 /api/hr/v1/home/）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_control_center import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
    path("overview", views.hr_overview, name="hr-overview"),
    path("todos", views.hr_todos, name="hr-todos"),
    path("alerts", views.hr_alerts, name="hr-alerts"),
    path("workforce", views.hr_workforce, name="hr-workforce"),
    path("actions", views.hr_actions, name="hr-actions"),
]
