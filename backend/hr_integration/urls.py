from django.urls import path
from . import views, sso_views

urlpatterns = [
    path("sso/<uuid:connection_id>/start/", sso_views.start, name="hr-sso-start"),
    path("sso/<uuid:connection_id>/callback/", sso_views.callback, name="hr-sso-callback"),
    path("sso/<uuid:connection_id>/ldap/", sso_views.ldap_login, name="hr-sso-ldap"),
    path("sso/logout/", sso_views.sso_logout, name="hr-sso-logout"),
    path("settings/integration-hub/", views.hub, name="hr-integration-hub"),
    path("settings/integration-hub/new/", views.connection_create, name="hr-integration-create"),
    path("settings/integration-hub/connections/<uuid:connection_id>/", views.connection_detail, name="hr-integration-connection"),
    path("settings/integration-hub/connections/<uuid:connection_id>/test/", views.run_test, name="hr-integration-test"),
    path("settings/integration-hub/connections/<uuid:connection_id>/mappings/<uuid:profile_id>/", views.profile_detail, name="hr-integration-profile"),
    path("settings/integration-hub/connections/<uuid:connection_id>/mappings/<uuid:profile_id>/delete/", views.mapping_profile_delete, name="hr-integration-profile-delete"),
    path("settings/integration-hub/connections/<uuid:connection_id>/mappings/<uuid:profile_id>/fields/<uuid:field_id>/delete/", views.field_mapping_delete, name="hr-integration-field-delete"),
    path("api/v1/system/integration-hub/connections/<uuid:connection_id>/contract/", views.contract_api, name="hr-integration-contract-api"),
]
