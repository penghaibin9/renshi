"""
hr_staff/urls.py —— HR03 页面路由。

统一前缀 /hr/staff/：
- /hr/staff/                          HR03-01 名册
- /hr/staff/{staff_id}                HR03-02 主档
- /hr/staff/{staff_id}/assignments    HR03-03 任职履历

Legacy 兼容：迁移期保留 /employee/employee-view-new/ 指向旧入口，最终菜单指向 /hr/staff。
"""

from django.urls import path

from hr_staff import views

urlpatterns = [
    path("", views.staff_list, name="hr03-staff-list"),
    path("<uuid:staff_id>/", views.staff_profile, name="hr03-staff-profile"),
    path(
        "<uuid:staff_id>/assignments",
        views.assignment_history,
        name="hr03-staff-assignments",
    ),
]
