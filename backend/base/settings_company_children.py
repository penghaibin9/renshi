"""One request-safe implementation of the school settings child views."""

from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from base.cbv.company import (
    CompanyListView as LegacyCompanyListView,
    CompanyNavView as LegacyCompanyNavView,
)
from base.models import Company
from base.settings_center import _require_permission, _selected_company
from platform_access.services import is_platform_operator


class ScopedCompanyListView(LegacyCompanyListView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Never mutate dictionaries shared by different view instances/users.
        self.actions = [dict(action) for action in self.actions]
        for action in self.actions:
            attrs = str(action.get("attrs") or "")
            if "{get_update_url}" in attrs:
                action["attrs"] = attrs.replace(
                    "{get_update_url}", "/settings/company-update/{pk}/"
                )

    def dispatch(self, request, *args, **kwargs):
        _selected_company(request)
        if not is_platform_operator(request.user):
            self.actions = [
                action for action in self.actions
                if str(action.get("action") or "").lower() != str(_("Delete")).lower()
            ]
            self.bulk_update = False
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self, queryset=None, filtered=False, *args, **kwargs):
        selected = _selected_company(self.request)
        return super().get_queryset(
            *args, queryset=Company.objects.filter(id=selected.id),
            filtered=filtered, **kwargs,
        )


class ScopedCompanyNavView(LegacyCompanyNavView):
    def dispatch(self, request, *args, **kwargs):
        _selected_company(request)
        if not is_platform_operator(request.user):
            self.create_attrs = ""
        return super().dispatch(request, *args, **kwargs)


@login_required
@require_GET
def company_list(request, *args, **kwargs):
    _require_permission(request, "base.view_company")
    _selected_company(request)
    return ScopedCompanyListView.as_view()(request, *args, **kwargs)


@login_required
@require_GET
def company_navbar(request, *args, **kwargs):
    _require_permission(request, "base.view_company")
    _selected_company(request)
    return ScopedCompanyNavView.as_view()(request, *args, **kwargs)
