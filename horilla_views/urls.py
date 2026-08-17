"""
horilla_views/urls.py
"""

from django.urls import path

from horilla.legacy_hr_cutover import protect_retired_legacy_model_write
from horilla_views import views
from horilla_views.generic.cbv import history
from horilla_views.generic.cbv.views import (
    HorillaListView,
    ReloadMessages,
    dispatch_profile_tab,
)

_generic_delete = protect_retired_legacy_model_write(
    views.HorillaDeleteConfirmationView.as_view(),
    surface="generic-delete",
    write_methods={"POST"},
)
_kanban_sequence = protect_retired_legacy_model_write(
    views.update_kanban_sequence,
    surface="update-kanban-sequence",
)
_kanban_item_group = protect_retired_legacy_model_write(
    views.update_kanban_item_group,
    surface="update-kanban-item-group",
)
_kanban_group_sequence = protect_retired_legacy_model_write(
    views.update_kanban_group_sequence,
    surface="update-kanban-group-sequence",
)
_history_revert = protect_retired_legacy_model_write(
    history.HorillaHistoryView.as_view(),
    surface="history-revert",
    block_methods={"POST"},
    write_methods={"POST"},
)
_generic_history = protect_retired_legacy_model_write(
    history.HorillaHistoryView.as_view(),
    surface="generic-history-revert",
    block_methods={"POST"},
    write_methods={"POST"},
)

urlpatterns = [
    path("toggle-columns/", views.ToggleColumn.as_view(), name="toggle-columns"),
    path("active-tab/", views.ActiveTab.as_view(), name="active-tab"),
    path("active-group/", views.ActiveGroup.as_view(), name="cbv-active-group"),
    path("reload-field/", views.ReloadField.as_view(), name="reload-field"),
    path("reload-messages/", ReloadMessages.as_view(), name="reload-messages"),
    path("saved-filter/", views.SavedFilter.as_view(), name="saved-filter"),
    path(
        "saved-filter/<int:pk>/",
        views.SavedFilter.as_view(),
        name="saved-filter-update",
    ),
    path(
        "delete-saved-filter/<int:pk>/",
        views.DeleteSavedFilter.as_view(),
        name="delete-saved-filter",
    ),
    path(
        "active-hnv-view-type/",
        views.ActiveView.as_view(),
        name="active-hnv-view-type",
    ),
    path(
        "search-in-instance-ids/",
        views.SearchInIds.as_view(),
        name="search-in-instance-ids",
    ),
    path(
        "last-applied-filter/",
        views.LastAppliedFilter.as_view(),
        name="last-applied-filter",
    ),
    path(
        "generic-delete/",
        _generic_delete,
        name="generic-delete",
    ),
    path(
        "horilla-history-revert/<int:pk>/<int:history_id>/",
        _history_revert,
        name="history-revert",
    ),
    path(
        "generic-history/<int:pk>/",
        _generic_history,
        name="generic-history",
    ),
    path(
        "update-kanban-sequence/",
        _kanban_sequence,
        name="update-kanban-sequence",
    ),
    path(
        "update-kanban-item-group/",
        _kanban_item_group,
        name="update-kanban-item-group",
    ),
    path(
        "get-kanban-card-count/",
        views.get_kanban_card_count,
        name="get-kanban-card-count",
    ),
    path(
        "update-kanban-group-sequence/",
        _kanban_group_sequence,
        name="update-kanban-group-sequence",
    ),
    path(
        "dynamic-path/<str:field>/<str:session_key>/",
        views.DynamicView.as_view(),
        name="dynamic-path",
    ),
    path("export-list-view/<slug:short_id>/", views.export_data, name="export-list"),
    path(
        "hzp-tab/<str:tab_key>/<int:pk>/",
        dispatch_profile_tab,
        name="hzp-profile-tab",
    ),
]
