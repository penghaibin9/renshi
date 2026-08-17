"""
hr_external/urls.py —— HR08 页面路由（S1 骨架 + S3 外聘教师库）。

工作区（§0）：
- HR08-01 外聘教师库  /hr/external-teachers/            （S3）
- HR08-02 产业教授    /hr/external-teachers/industry/   （S4）
- HR08-03 聘用审批    /hr/external-teachers/hiring/     （S5）
- HR08-04 任务矩阵    /hr/external-teachers/tasks/      （S7）
- HR08-05 续聘/退出   /hr/external-teachers/renewals/、/exits/（S8）
"""

from django.urls import path

from hr_external import views

urlpatterns = [
    path("", views.external_teachers_home, name="hr08-home"),
    path("pool/", views.external_teacher_pool, name="hr08-pool"),
    path("renewals/", views.renewals_home, name="hr08-renewals-home"),
    path("exits/", views.exits_home, name="hr08-exits-home"),
    path(
        "tasks/",
        views.tasks_home,
        name="hr08-tasks-home",
    ),
    path(
        "hiring/<uuid:case_id>/",
        views.hiring_detail,
        name="hr08-hiring-detail",
    ),
    path("hiring/", views.hiring_home, name="hr08-hiring-home"),
    path(
        "industry/<uuid:engagement_id>/",
        views.industry_engagement_detail,
        name="hr08-industry-engagement-detail",
    ),
    path("industry/", views.industry_home, name="hr08-industry-home"),
    path(
        "<uuid:profile_id>/",
        views.external_teacher_profile,
        name="hr08-profile-detail",
    ),
]
