from django.urls import path

from . import api, publicity_api, result_api

app_name = "hr_title_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "applications/<uuid:case_id>/qualification-decision/",
        api.qualification_decision,
        name="qualification-decision",
    ),
    path(
        "applications/<uuid:case_id>/review-rounds/",
        api.open_review_round,
        name="review-round-open",
    ),
    path(
        "review-rounds/<uuid:round_id>/assignments/",
        api.create_review_assignment,
        name="review-assignment-create",
    ),
    path(
        "review-assignments/<uuid:assignment_id>/respond/",
        api.respond_review_assignment,
        name="review-assignment-respond",
    ),
    path(
        "review-assignments/<uuid:assignment_id>/ballots/",
        api.submit_review_ballot,
        name="review-ballot-submit",
    ),
    path(
        "review-rounds/<uuid:round_id>/close/",
        api.close_review_round,
        name="review-round-close",
    ),
    path(
        "applications/<uuid:case_id>/publicities/",
        publicity_api.open_publicity,
        name="publicity-open",
    ),
    path(
        "publicities/<uuid:publicity_id>/appeals/",
        publicity_api.lodge_appeal,
        name="appeal-lodge",
    ),
    path(
        "appeals/<uuid:appeal_id>/resolve/",
        publicity_api.resolve_appeal,
        name="appeal-resolve",
    ),
    path(
        "publicities/<uuid:publicity_id>/close/",
        publicity_api.close_publicity,
        name="publicity-close",
    ),
    path(
        "publicities/<uuid:publicity_id>/cancel/",
        publicity_api.cancel_publicity,
        name="publicity-cancel",
    ),
    path(
        "applications/<uuid:case_id>/result/effective/",
        result_api.make_effective,
        name="result-effective",
    ),
    path(
        "results/<uuid:result_id>/revisions/",
        result_api.revise_result,
        name="result-revise",
    ),
    path(
        "results/<uuid:result_id>/revoke/",
        result_api.revoke_result,
        name="result-revoke",
    ),
]
