"""
hr_structure/urls.py

HR02 页面路由（挂载 /hr/structure/ 下）：
  /hr/structure/organizations        → HR02-01 组织机构
  /hr/structure/relations            → HR02-02 党政组织与业务关系
  /hr/structure/staffing-plans       → HR02-03 编制方案
  /hr/structure/post-catalogs        → HR02-04 岗位目录
  /hr/structure/positions            → HR02-05 岗位编制台账
  /hr/structure/history              → HR02-06 组织岗位历史

API 前缀：/api/hr/v1/structure/*（见 api/urls.py）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_structure import views

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="hr-structure-organizations", permanent=False),
    ),
    path(
        "organizations",
        views.hr_organizations,
        name="hr-structure-organizations",
    ),
    path(
        "relations",
        RedirectView.as_view(pattern_name="hr-structure-organizations", permanent=False),
    ),
    path(
        "staffing-plans",
        RedirectView.as_view(pattern_name="hr-structure-organizations", permanent=False),
    ),
    path(
        "post-catalogs",
        RedirectView.as_view(pattern_name="hr-structure-organizations", permanent=False),
    ),
    path(
        "positions",
        views.hr_positions,
        name="hr-structure-positions",
    ),
]
