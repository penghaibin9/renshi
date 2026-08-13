from django.urls import path

from . import api

app_name = "hr_exit_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
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
