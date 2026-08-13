from django.urls import path

from . import api, term_api

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
    path(
        "appointment-facts/<uuid:fact_id>/term/",
        term_api.register_term,
        name="term-register",
    ),
    path(
        "terms/<uuid:term_id>/expiring/",
        term_api.mark_expiring,
        name="term-mark-expiring",
    ),
    path(
        "terms/<uuid:term_id>/expired/",
        term_api.mark_expired,
        name="term-mark-expired",
    ),
    path(
        "terms/<uuid:term_id>/renewals/",
        term_api.open_renewal,
        name="renewal-open",
    ),
    path(
        "renewals/<uuid:renewal_id>/decision/",
        term_api.decide_renewal,
        name="renewal-decision",
    ),
    path(
        "terms/<uuid:term_id>/changes/",
        term_api.open_change,
        name="term-change-open",
    ),
    path(
        "term-changes/<uuid:change_id>/decision/",
        term_api.decide_change,
        name="term-change-decision",
    ),
]
