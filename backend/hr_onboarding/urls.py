"""
hr_onboarding/urls.py

HR05 正式页面路由（挂载 /hr/onboarding/ 下）：
  /hr/onboarding/prehires           → HR05-01 待报到人员
  /hr/onboarding/prehires/:caseId    → case 详情
  /hr/onboarding/reporting          → HR05-02 报到登记
  /hr/onboarding/reporting/:caseId  → case 报到页
  /hr/onboarding/materials          → HR05-03 材料核验工作台
  /hr/onboarding/collaboration      → HR05-04 协同任务中心
  /hr/onboarding/probations         → HR05-05 试用与转正列表
  /hr/onboarding/probations/:id     → 试用详情

API 路由见 hr_onboarding/api/urls.py（独立前缀 /api/hr/v1/onboarding/）。
Portal 路由（公开，token 鉴权）单独挂载，禁带 tenant_id。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_onboarding import views

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="hr05-prehires", permanent=False),
    ),
    path(
        "prehires",
        views.hr05_prehires,
        name="hr05-prehires",
    ),
    path(
        "prehires/<uuid:case_id>",
        views.hr05_case_detail,
        name="hr05-case-detail",
    ),
    path(
        "reporting",
        views.hr05_reporting,
        name="hr05-reporting",
    ),
    path(
        "reporting/<uuid:case_id>",
        views.hr05_report_checkin,
        name="hr05-report-checkin",
    ),
    path(
        "materials",
        views.hr05_material_workspace,
        name="hr05-material-workspace",
    ),
    path(
        "collaboration",
        views.hr05_collaboration_center,
        name="hr05-collaboration-center",
    ),
    path(
        "probations",
        views.hr05_probation_list,
        name="hr05-probations",
    ),
    path(
        "probations/<uuid:probation_id>",
        views.hr05_probation_detail,
        name="hr05-probation-detail",
    ),
]
