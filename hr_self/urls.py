from django.urls import path
from . import views

app_name = "hr_self"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("services/", views.workspace, {"section": "services"}, name="services"),
    path("todos/", views.workspace, {"section": "todos"}, name="todos"),
    path("progress/", views.workspace, {"section": "progress"}, name="progress"),
    path("files/", views.workspace, {"section": "files"}, name="files"),
    path("payroll-contracts/", views.workspace, {"section": "payroll-contracts"}, name="payroll-contracts"),
]
