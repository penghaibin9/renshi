from django.urls import path
from . import views

urlpatterns = [
    path("settings/hr-configuration/", views.configuration_center, name="hr-configuration-center"),
    path("settings/hr-configuration/workflows/<uuid:workflow_id>/", views.workflow_detail, name="hr-configuration-workflow"),
    path("settings/hr-configuration/workflows/<uuid:workflow_id>/<str:kind>/<uuid:object_id>/edit/", views.component_edit, name="hr-configuration-component-edit"),
    path("settings/hr-configuration/workflows/<uuid:workflow_id>/<str:kind>/<uuid:object_id>/delete/", views.component_delete, name="hr-configuration-component-delete"),
    path("api/v1/system/hr-configuration/workflows/<uuid:workflow_id>/published/", views.published_config_api, name="hr-configuration-published-api"),
]
