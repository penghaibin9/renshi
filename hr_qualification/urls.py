"""HR09 教师资格管理端页面路由。"""

from django.urls import path

from hr_qualification import views

app_name = "hr_qualification"

urlpatterns = [
    path("", views.qualification_workspace, {"section": "overview"}, name="hr09-overview"),
    path("credentials/", views.qualification_workspace, {"section": "credentials"}, name="hr09-credentials"),
    path("risks/", views.qualification_workspace, {"section": "risks"}, name="hr09-risks"),
]
