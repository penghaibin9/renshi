"""HR07 合同与聘用管理端页面路由。"""

from django.urls import path

from hr_contracts import views

app_name = "hr_contracts"

urlpatterns = [
    path("", views.contract_workspace, {"section": "ledger"}, name="ledger"),
    path("rules/", views.contract_workspace, {"section": "rules"}, name="rules"),
    path("signing/", views.contract_workspace, {"section": "signing"}, name="signing"),
    path("changes/", views.contract_workspace, {"section": "changes"}, name="changes"),
    path("risks/", views.contract_workspace, {"section": "risks"}, name="risks"),
]
