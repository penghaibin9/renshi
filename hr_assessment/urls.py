"""HR12 Assessment — 页面路由（占位）。当前 S1 只做基础骨架，页面在 S2-S9 逐步添加。"""

from django.urls import path

from hr_assessment import views

app_name = "hr_assessment"

urlpatterns = [
    # S1 占位首页 — 后续替换为完整 Assessment 首页
    path("", views.index, name="hr12-index"),
]
