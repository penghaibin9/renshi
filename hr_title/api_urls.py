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
]
