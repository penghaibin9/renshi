"""Harden the legacy System Settings entry points.

The settings UI predates tenant-scoped RBAC and several endpoints trusted the
session value without proving that it named an authorised concrete company.
These views preserve the existing templates and URL contracts while enforcing
one school per write, object-level concealment, method restrictions, row locks,
and separate view/change permissions.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from base import views as legacy_views
from base.auth_backends import get_allowed_company_ids
from base.forms import CompanyForm, DynamicPaginationForm
from base.models import Company, DynamicPagination
from horilla.http.response import HorillaRedirect


SYSTEM_PREFERENCES_VIEW_PERMISSIONS = (
    "base.change_announcementexpire",
    "base.view_dynamicpagination",
    "horilla_audit.view_accountblockunblock",
    "employee.change_employeegeneralsetting",
    "horilla_audit.view_historytrackingfields",
    "payroll.view_payrollsettings",
    "base.view_company",
    "base.view_companylanguagesetting",
)

TIME_FORMATS = frozenset({"HH:mm", "hh:mm A", "HH:mm:ss", "hh:mm:ss A"})


def _has_any_permission(user, permissions: Iterable[str]) -> bool:
    return bool(user.is_superuser or any(user.has_perm(code) for code in permissions))


def _require_permission(request, permission: str) -> None:
    if not request.user.has_perm(permission):
        raise PermissionDenied


def _require_any_permission(request, permissions: Iterable[str]) -> None:
    if not _has_any_permission(request.user, permissions):
        raise PermissionDenied


def _selected_company(request) -> Company:
    """Return one explicit authorised school; never infer or accept ``all``."""

    selected = request.session.get("selected_company")
    if selected in (None, "", "all"):
        raise PermissionDenied(_("Select one school before changing settings."))
    try:
        company_id = int(selected)
    except (TypeError, ValueError) as exc:
        raise Http404 from exc

    if not request.user.is_superuser:
        allowed = get_allowed_company_ids(request.user)
        if company_id not in allowed:
            # Conceal whether another tenant's company identifier exists.
            raise Http404
    return get_object_or_404(Company.objects.only("id", "company"), id=company_id)


def _locked_selected_company(request) -> Company:
    selected = _selected_company(request)
    return Company.objects.select_for_update().get(id=selected.id)


def _date_formats() -> set[str]:
    values = set()
    for item in getattr(settings, "HORILLA_DATE_FORMATS", ()):
        if isinstance(item, (tuple, list)):
            if item:
                values.add(str(item[0]))
        else:
            values.add(str(item))
    return values


@login_required
@require_http_methods(["GET", "POST"])
def system_preferences_settings_view(request):
    """Render the merged preference page only inside a concrete school."""

    _require_any_permission(request, SYSTEM_PREFERENCES_VIEW_PERMISSIONS)
    _selected_company(request)
    if request.method == "POST":
        # Announcement expiry is a singleton platform preference.  A tenant
        # role may view other controls on the merged page but cannot mutate it
        # unless it owns the explicit change permission in the selected school.
        _require_permission(request, "base.change_announcementexpire")
    return legacy_views.system_preferences_settings_view(request)


@login_required
@require_http_methods(["GET", "POST"])
def pagination_settings_view(request):
    """Read or save the current user's pagination preference safely."""

    _selected_company(request)
    if request.method == "GET":
        _require_permission(request, "base.view_dynamicpagination")
        instance = DynamicPagination.objects.filter(user_id=request.user).first()
        return render(
            request,
            "base/dynamic_pagination/pagination_settings.html",
            {"form": DynamicPaginationForm(instance=instance)},
        )

    _require_permission(request, "base.change_dynamicpagination")
    with transaction.atomic():
        instance = (
            DynamicPagination.objects.select_for_update()
            .filter(user_id=request.user)
            .first()
        )
        form = DynamicPaginationForm(request.POST, instance=instance)
        if not form.is_valid():
            return JsonResponse(
                {"success": False, "errors": form.errors.get_json_data()},
                status=400,
            )
        preference = form.save(commit=False)
        preference.user_id = request.user
        preference.save()
    return JsonResponse(
        {"success": True, "pagination": preference.pagination},
        status=200,
    )


@login_required
@require_POST
def save_date_format(request):
    _require_permission(request, "base.change_company")
    selected_format = (request.POST.get("selected_format") or "").strip()
    if selected_format not in _date_formats():
        return JsonResponse(
            {"success": False, "error": "Invalid date format."},
            status=400,
        )
    with transaction.atomic():
        company = _locked_selected_company(request)
        company.date_format = selected_format
        company.save(update_fields=["date_format"])
    return JsonResponse(
        {
            "success": True,
            "company_id": company.id,
            "selected_format": company.date_format,
        }
    )


@login_required
@require_GET
def get_date_format(request):
    _require_permission(request, "base.view_company")
    company = _selected_company(request)
    company.refresh_from_db(fields=["date_format"])
    return JsonResponse(
        {"selected_format": company.date_format or "MMM. D, YYYY"}
    )


@login_required
@require_POST
def save_time_format(request):
    _require_permission(request, "base.change_company")
    selected_format = (request.POST.get("selected_format") or "").strip()
    if selected_format not in TIME_FORMATS:
        return JsonResponse(
            {"success": False, "error": "Invalid time format."},
            status=400,
        )
    with transaction.atomic():
        company = _locked_selected_company(request)
        company.time_format = selected_format
        company.save(update_fields=["time_format"])
    return JsonResponse(
        {
            "success": True,
            "company_id": company.id,
            "selected_format": company.time_format,
        }
    )


@login_required
@require_GET
def get_time_format(request):
    _require_permission(request, "base.view_company")
    company = _selected_company(request)
    company.refresh_from_db(fields=["time_format"])
    return JsonResponse({"selected_format": company.time_format or "hh:mm A"})


@login_required
@require_GET
def default_export_access_settings_view(request):
    _require_permission(request, "base.view_defaultexportpermission")
    _selected_company(request)
    return legacy_views.default_export_access_settings_view(request)


@login_required
@require_POST
def enable_default_export_access(request):
    _require_permission(request, "base.change_defaultexportpermission")
    # Locking the tenant row serialises competing toggles and guarantees the
    # legacy implementation cannot create a company=NULL global setting.
    with transaction.atomic():
        _locked_selected_company(request)
        return legacy_views.enable_default_export_access(request)


@login_required
@require_POST
def update_language_settings(request):
    _require_permission(request, "base.change_companylanguagesetting")
    with transaction.atomic():
        _locked_selected_company(request)
        return legacy_views.update_language_settings(request)


@login_required
@require_GET
def company_view(request):
    _require_permission(request, "base.view_company")
    company = _selected_company(request)
    return render(
        request,
        "base/company/company.html",
        {"companies": Company.objects.filter(id=company.id), "model": Company()},
    )


@login_required
@require_http_methods(["GET", "POST"])
def company_update(request, id, **kwargs):
    del kwargs
    _require_permission(request, "base.change_company")
    selected = _selected_company(request)
    # Settings writes are bound to the selected school, even when the user has
    # memberships in more than one school.  A mismatched identifier is hidden.
    if int(id) != selected.id:
        raise Http404

    with transaction.atomic():
        company = Company.objects.select_for_update().get(id=selected.id)
        form = CompanyForm(
            request.POST or None,
            request.FILES or None,
            instance=company,
        )
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, _("Company updated"))
            return HorillaRedirect(request)

    return render(
        request,
        "base/company/company_form.html",
        {"form": form, "company": company},
    )
