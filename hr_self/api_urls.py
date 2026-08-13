from django.urls import path

from . import api, catalog_api

app_name = "hr_self_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path("bootstrap/", api.bootstrap, name="bootstrap"),
    path("services/", catalog_api.service_catalog, name="service_catalog"),
    path("services/<str:service_code>/pin/", api.service_pin, name="service_pin"),
]
