from django.urls import path
from . import views

app_name = "hr_self"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("services/", views.workspace, {"section": "services"}, name="services"),
    path("todos/", views.workspace, {"section": "todos"}, name="todos"),
    path("progress/", views.workspace, {"section": "progress"}, name="progress"),
    path("files/", views.workspace, {"section": "files"}, name="files"),
    path("payslips/", views.workspace, {"section": "payslips"}, name="payslips"),
    path("contracts/", views.workspace, {"section": "contracts"}, name="contracts"),
    # Compatibility entry; keeps old links working without accepting staff_id.
    path("payroll-contracts/", views.workspace, {"section": "payslips"}, name="payroll_contracts_compat"),
]
