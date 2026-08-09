"""
hr_changes/urls.py —— HR06 页面路由。

统一前缀 /hr/changes/（由 apps.ready() 挂载）。
"""

from django.urls import path

from hr_changes import views

urlpatterns = [
    path("", views.change_center, name="hr06-change-center"),
    path("changes", views.change_center, name="hr06-change-center-alt"),
    path("new", views.change_new, name="hr06-change-new"),
    path("future", views.future_changes, name="hr06-changes-future-page"),
    path("<uuid:case_id>", views.change_detail, name="hr06-change-detail"),
    path("<uuid:case_id>/preview", views.change_preview, name="hr06-change-preview"),
    # S4-S7 占位（当前阶段重定向到中心，避免 404）
    path("transfers", views.change_center, name="hr06-transfers"),
    path("job-identity", views.change_center, name="hr06-job-identity"),
    path("secondments", views.change_center, name="hr06-secondments"),
    path("ledger", views.change_center, name="hr06-ledger"),
]
