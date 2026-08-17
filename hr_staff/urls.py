"""
hr_staff/urls.py —— HR03 页面路由。

统一前缀 /hr/staff/：
- /hr/staff/                          HR03-01 名册
- /hr/staff/{staff_id}                HR03-02 主档
- /hr/staff/{staff_id}/assignments    HR03-03 任职履历
- /hr/staff/{staff_id}/backgrounds    HR03-04 教育资格
- /hr/staff/{staff_id}/materials      HR03-05 材料档案
- /hr/staff/{staff_id}/corrections    HR03-06 更正与历史
- /hr/staff/data-quality              数据质量异常中心

历史 `*-page` 浏览器地址继续保留兼容，不删除旧书签。
"""

from django.urls import path

from hr_staff import views

urlpatterns = [
    path("", views.staff_list, name="hr03-staff-list"),
    path("data-quality/", views.data_quality, name="hr03-data-quality"),
    path("<uuid:staff_id>/", views.staff_profile, name="hr03-staff-profile"),
    path("<uuid:staff_id>/assignments", views.assignment_history, name="hr03-staff-assignments"),
    path("<uuid:staff_id>/backgrounds", views.background_facts, name="hr03-staff-backgrounds"),
    path("<uuid:staff_id>/materials", views.materials, name="hr03-staff-materials"),
    path("<uuid:staff_id>/corrections", views.corrections, name="hr03-staff-corrections"),
    path("<uuid:staff_id>/backgrounds-page", views.background_facts, name="hr03-staff-backgrounds-legacy-page"),
    path("<uuid:staff_id>/materials-page", views.materials, name="hr03-staff-materials-legacy-page"),
    path("<uuid:staff_id>/corrections-page", views.corrections, name="hr03-staff-corrections-legacy-page"),
]
