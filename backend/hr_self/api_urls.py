from django.urls import path

from . import api, catalog_api, command_api

app_name = "hr_self_api"
urlpatterns = [
    path("commands/", command_api.workspace, name="self-commands"),
    path("commands/corrections/", command_api.corrections, name="self-correction-create"),
    path("commands/corrections/<uuid:case_id>/", command_api.correction_action, name="self-correction-action"),
    path("commands/materials/", command_api.upload, name="self-material-upload"),
    path("commands/retirement/", command_api.flex_create, name="self-retirement-create"),
    path("commands/retirement/<uuid:application_id>/", command_api.flex_action, name="self-retirement-action"),
    path("dashboard/", api.dashboard, name="dashboard"),
    path("bootstrap/", api.bootstrap, name="bootstrap"),
    path("records/", api.self_records, name="self_records"),
    path("services/", catalog_api.service_catalog, name="service_catalog"),
    path("services/<str:service_code>/pin/", api.service_pin, name="service_pin"),
]
