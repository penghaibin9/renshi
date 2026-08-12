"""HR07 合同管理页面路由。"""

from django.urls import path

from hr_contracts import views

app_name = "hr_contracts"

urlpatterns = [
    path("", views.workspace, {"section": "overview"}, name="hr07-overview"),
    path("agreements/", views.workspace, {"section": "agreements"}, name="hr07-agreements"),
    path("signing/", views.workspace, {"section": "signing"}, name="hr07-signing"),
    path("renewals/", views.workspace, {"section": "renewals"}, name="hr07-renewals"),
    path("changes/", views.workspace, {"section": "changes"}, name="hr07-changes"),
    path("terminations/", views.workspace, {"section": "terminations"}, name="hr07-terminations"),
    path("versions/", views.workspace, {"section": "versions"}, name="hr07-versions"),
]
