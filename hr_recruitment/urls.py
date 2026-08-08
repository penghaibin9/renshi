"""
hr_recruitment/urls.py

HR04 页面路由（挂载 /hr/recruitment/ 下）。
S1 阶段：占位骨架；S3-S8 逐模块挂载：
  /hr/recruitment/plans            → HR04-01 年度用人计划
  /hr/recruitment/campaigns        → HR04-02 招聘项目与岗位（默认入口/控制台）
  /hr/recruitment/candidates       → HR04-03 人才库与应聘者
  /hr/recruitment/qualification    → HR04-04 资格审查
  /hr/recruitment/assessment       → HR04-05 考试面试与考察
  /hr/recruitment/proposed-hires   → HR04-06 录用与人才引进

API 路由见 hr_recruitment/api/urls.py（独立前缀 /api/hr/v1/recruitment/）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_recruitment import views

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="hr04-campaigns", permanent=False),
    ),
    # S3 挂载点
    path(
        "plans",
        views.hr04_plans,
        name="hr04-plans",
    ),
    path(
        "campaigns",
        views.hr04_campaigns,
        name="hr04-campaigns",
    ),
    path(
        "candidates",
        RedirectView.as_view(pattern_name="hr04-campaigns", permanent=False),
        name="hr04-candidates",
    ),
    path(
        "qualification",
        RedirectView.as_view(pattern_name="hr04-campaigns", permanent=False),
        name="hr04-qualification",
    ),
    path(
        "assessment",
        RedirectView.as_view(pattern_name="hr04-campaigns", permanent=False),
        name="hr04-assessment",
    ),
    path(
        "proposed-hires",
        RedirectView.as_view(pattern_name="hr04-campaigns", permanent=False),
        name="hr04-proposed-hires",
    ),
]
