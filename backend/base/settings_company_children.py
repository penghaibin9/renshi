"""Tenant-safe HTMX child views for the System Settings company page.

Django assigns ``self.request`` in ``View.setup`` immediately before
``dispatch``.  The first hardened implementation read it from ``__init__``, so
the company table and navbar could fail before a request was attached.  Keep
request-independent action rewriting in construction and perform tenant/user
checks only from dispatch or later hooks.
"""

from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from base.cbv.company import (
    CompanyListView as LegacyCompanyListView,
    CompanyNavView as LegacyCompanyNavView,
)
from base.models import Company
from base.settings_center import _require_permission, _selected_company


class ScopedCompanyListView(LegacyCompanyListView):
    """Render exactly the selected school in the legacy generic table."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for action in self.actions:
            attrs = str(action.get("attrs") or "")
            if "{get_update_url}" in attrs:
                action["attrs"] = attrs.replace(
                    "{get_update_url}",
                    "/settings/company-update/{pk}/",
                )

    def dispatch(self, request, *args, **kwargs):
        _selected_company(request)
        if not request.user.is_superuser:
            self.actions = [
                action
                for action in self.actions
                if str(action.get("action") or "").lower()
                != str(_("Delete")).lower()
            ]
            self.bulk_update = False
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self, queryset=None, filtered=False, *args, **kwargs):
        selected = _selected_company(self.request)
        return super().get_queryset(
            queryset=Company.objects.filter(id=selected.id),
            filtered=filtered,
            *args,
            **kwargs,
        )


class ScopedCompanyNavView(LegacyCompanyNavView):
    """Show navigation for one school without tenant-creation controls."""

    def dispatch(self, request, *args, **kwargs):
        _selected_company(request)
        if not request.user.is_superuser:
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
