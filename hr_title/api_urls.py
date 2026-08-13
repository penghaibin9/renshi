from django.urls import path

from . import api

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
        api.review_round_open,
        name="review-round-open",
    ),
    path(
        "review-rounds/<uuid:round_id>/assignments/",
        api.review_assignment_create,
        name="review-assignment-create",
    ),
    path(
        "review-assignments/<uuid:assignment_id>/response/",
        api.review_assignment_respond,
        name="review-assignment-respond",
    ),
    path(
        "review-assignments/<uuid:assignment_id>/ballot/",
        api.review_ballot_submit,
        name="review-ballot-submit",
    ),
    path(
        "review-rounds/<uuid:round_id>/close/",
        api.review_round_close,
        name="review-round-close",
    ),
]
