from django.urls import path

from . import api

app_name = "hr_appointment_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "applications/<uuid:case_id>/ranking-result/",
        api.ranking_result,
        name="ranking-result",
    ),
    path(
        "applications/<uuid:case_id>/publicity/",
        api.open_publicity,
        name="publicity-open",
    ),
    path(
        "publicities/<uuid:publicity_id>/objections/",
        api.submit_publicity_objection,
        name="publicity-objection-submit",
    ),
    path(
        "publicity-objections/<uuid:objection_id>/resolve/",
        api.resolve_publicity_objection,
        name="publicity-objection-resolve",
    ),
    path(
        "publicities/<uuid:publicity_id>/close/",
        api.close_publicity,
        name="publicity-close",
    ),
    path(
        "publicities/<uuid:publicity_id>/cancel/",
        api.cancel_publicity,
        name="publicity-cancel",
    ),
]
