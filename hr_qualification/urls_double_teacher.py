"""HR09 双师型认定管理端页面路由。"""

from django.urls import path

from hr_qualification import views

app_name = "hr_double_teacher"

urlpatterns = [
    path("", views.qualification_workspace, {"section": "batches"}, name="hr09-double-teacher-batches"),
    path("applications/", views.qualification_workspace, {"section": "applications"}, name="hr09-double-teacher-applications"),
    path("recognitions/", views.qualification_workspace, {"section": "recognitions"}, name="hr09-double-teacher-recognitions"),
]
