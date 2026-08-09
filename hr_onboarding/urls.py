"""
hr_onboarding/urls.py

HR05 页面路由（挂载 /hr/onboarding/ 下）。
S1 阶段：占位骨架；S3-S7 逐模块挂载：
  /hr/onboarding/prehires           → HR05-01 待报到人员
  /hr/onboarding/prehires/:caseId    → case 详情
  /hr/onboarding/reporting          → HR05-02 报到登记
  /hr/onboarding/materials          → HR05-03 材料核验
  /hr/onboarding/collaboration      → HR05-04 协同任务
  /hr/onboarding/probations         → HR05-05 试用与转正

API 路由见 hr_onboarding/api/urls.py（独立前缀 /api/hr/v1/onboarding/）。
Portal 路由（公开，token 鉴权）S3 单独挂载，禁带 tenant_id。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_onboarding import views

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
    ),
    # S3 挂载点（占位重定向到待报到列表，避免 404）
    path(
        "prehires",
        views.hr05_prehires,
        name="hr05-prehires",
    ),
    path(
        "reporting",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
        name="hr05-reporting",
    ),
    path(
        "materials",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
        name="hr05-materials",
    ),
    path(
        "collaboration",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
        name="hr05-collaboration",
    ),
    path(
        "probations",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
        name="hr05-probations",
    ),
]
