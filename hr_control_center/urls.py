"""
hr_control_center/urls.py

页面路由（挂载在 /hr/ 下）：
  /hr/            → 重定向到 overview
  /hr/overview    → HR01-01 人事总览
  /hr/todos       → HR01-02 我的待办（S4）
  /hr/alerts      → HR01-03 人事预警（S5）
  /hr/workforce   → HR01-04 队伍结构（S6）
  /hr/actions     → HR01-05 快捷办理（S7）

API 路由见 hr_control_center/api/urls.py（独立前缀 /api/hr/v1/home/）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_control_center import views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
    path("overview", views.hr_overview, name="hr-overview"),
    # S4/S5/S6/S7 页面后续实现（先重定向到总览，避免 dead link）
    path("todos", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
    path("alerts", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
    path("workforce", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
    path("actions", RedirectView.as_view(pattern_name="hr-overview", permanent=False)),
]
