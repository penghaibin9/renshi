from django.urls import path

from . import api

app_name = "hr_exit_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path("cases/", api.create_case, name="case-create"),
    path("cases/<uuid:case_id>/submit/", api.submit_case, name="case-submit"),
    path("cases/<uuid:case_id>/return/", api.return_case, name="case-return"),
    path("cases/<uuid:case_id>/approve/", api.approve_case, name="case-approve"),
    path("cases/<uuid:case_id>/reject/", api.reject_case, name="case-reject"),
    path("cases/<uuid:case_id>/cancel/", api.cancel_case, name="case-cancel"),
    path(
        "cases/<uuid:case_id>/handover/start/",
        api.begin_handover,
        name="case-handover-start",
    ),
    path(
        "cases/<uuid:case_id>/settlement/start/",
        api.begin_settlement,
        name="case-settlement-start",
    ),
    path(
        "cases/<uuid:case_id>/apply-effect/",
        api.apply_effect,
        name="case-effect-apply",
    ),
    path(
        "cases/<uuid:case_id>/handover-items/",
        api.create_handover_item,
        name="handover-item-create",
    ),
    path(
        "handover-items/<uuid:item_id>/complete/",
        api.complete_handover_item,
        name="handover-item-complete",
    ),
    path(
        "handover-items/<uuid:item_id>/waive/",
        api.waive_handover_item,
        name="handover-item-waive",
    ),
]
