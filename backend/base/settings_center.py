"""Canonical school settings handlers; platform actions use operator authority.

Old public URLs are preserved. Company list/navbar implementations live only in
settings_company_children; do not reintroduce request-dependent constructors.
"""

from __future__ import annotations

from collections.abc import Iterable

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
from base.cbv.company import CompanyCreateForm as LegacyCompanyCreateForm
from base.forms import CompanyForm, DynamicPaginationForm
from base.models import Company, DynamicPagination
from horilla.http.response import HorillaRedirect
from platform_access.services import (
    get_active_tenant_elevation,
    is_platform_operator,
    require_platform_operator,
)

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

DATE_FORMATS = frozenset(
    {
        "DD-MM-YYYY", "DD.MM.YYYY", "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD",
        "YYYY/MM/DD", "MMMM D, YYYY", "DD MMMM, YYYY", "MMM. D, YYYY",
        "D MMM. YYYY", "dddd, MMMM D, YYYY",
    }
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
    """Prove a concrete school; historical school superusers do not bypass it."""
    selected = request.session.get("selected_company")
    if selected in (None, "", "all"):
        raise PermissionDenied(_("Select one school before changing settings."))
    try:
        company_id = int(selected)
    except (TypeError, ValueError) as exc:
        raise Http404 from exc
    if company_id <= 0 or isinstance(selected, bool):
        raise Http404

    if is_platform_operator(request.user):
        if get_active_tenant_elevation(request, expected_company_id=company_id) is None:
            raise PermissionDenied(_("An active platform support session is required."))
    elif company_id not in get_allowed_company_ids(request.user):
        raise Http404
    return get_object_or_404(Company.objects.only("id", "company"), id=company_id)


def _locked_selected_company(request) -> Company:
    selected = _selected_company(request)
    return Company.objects.select_for_update().get(id=selected.id)


@login_required
@require_http_methods(["GET", "POST"])
def system_preferences_settings_view(request):
    _require_any_permission(request, SYSTEM_PREFERENCES_VIEW_PERMISSIONS)
    _selected_company(request)
    if request.method == "POST":
        require_platform_operator(request.user)
        _require_permission(request, "base.change_announcementexpire")
    return legacy_views.system_preferences_settings_view(request)


@login_required
@require_http_methods(["GET", "POST"])
def pagination_settings_view(request):
    _selected_company(request)
    if request.method == "GET":
        _require_permission(request, "base.view_dynamicpagination")
        instance = DynamicPagination.objects.filter(user_id=request.user).first()
        form = DynamicPaginationForm(instance=instance)
        return render(request, "base/dynamic_pagination/pagination_settings.html",
                      {"form": form, "pagination_form": form})
    _require_permission(request, "base.change_dynamicpagination")
    with transaction.atomic():
        instance = DynamicPagination.objects.select_for_update().filter(user_id=request.user).first()
        form = DynamicPaginationForm(request.POST, instance=instance)
        if not form.is_valid():
            return JsonResponse({"success": False, "errors": form.errors.get_json_data()}, status=400)
        preference = form.save(commit=False)
        preference.user_id = request.user
        preference.save()
    return JsonResponse({"success": True, "pagination": preference.pagination}, status=200)


@login_required
@require_POST
def save_date_format(request):
    _require_permission(request, "base.change_company")
    selected_format = (request.POST.get("selected_format") or "").strip()
    if selected_format not in DATE_FORMATS:
        return JsonResponse({"success": False, "error": "Invalid date format."}, status=400)
    with transaction.atomic():
        company = _locked_selected_company(request)
        company.date_format = selected_format
        company.save(update_fields=["date_format"])
    return JsonResponse({"success": True, "company_id": company.id, "selected_format": company.date_format})


@login_required
@require_GET
def get_date_format(request):
    _require_permission(request, "base.view_company")
    company = _selected_company(request)
    company.refresh_from_db(fields=["date_format"])
    return JsonResponse({"selected_format": company.date_format or "MMM. D, YYYY"})


@login_required
@require_POST
def save_time_format(request):
    _require_permission(request, "base.change_company")
    selected_format = (request.POST.get("selected_format") or "").strip()
    if selected_format not in TIME_FORMATS:
        return JsonResponse({"success": False, "error": "Invalid time format."}, status=400)
    with transaction.atomic():
        company = _locked_selected_company(request)
        company.time_format = selected_format
        company.save(update_fields=["time_format"])
    return JsonResponse({"success": True, "company_id": company.id, "selected_format": company.time_format})


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
    return render(request, "base/company/company.html",
                  {"companies": Company.objects.filter(id=company.id), "model": Company()})


@login_required
@require_GET
def company_list(request, *args, **kwargs):
    # Retain old imports, but delegate to the one request-safe implementation.
    from base.settings_company_children import company_list as handler
    return handler(request, *args, **kwargs)


@login_required
@require_GET
def company_navbar(request, *args, **kwargs):
    from base.settings_company_children import company_navbar as handler
    return handler(request, *args, **kwargs)


@login_required
@require_http_methods(["GET", "POST"])
def company_create_form(request, *args, **kwargs):
    require_platform_operator(request.user)
    _require_permission(request, "base.add_company")
    return LegacyCompanyCreateForm.as_view()(request, *args, **kwargs)


@login_required
@require_http_methods(["GET", "POST"])
def company_update(request, id, **kwargs):
    del kwargs
    _require_permission(request, "base.change_company")
    selected = _selected_company(request)
    if int(id) != selected.id:
        raise Http404
    with transaction.atomic():
        company = Company.objects.select_for_update().get(id=selected.id)
        form = CompanyForm(request.POST or None, request.FILES or None, instance=company)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, _("Company updated"))
            return HorillaRedirect(request)
    return render(request, "base/company/company_form.html", {"form": form, "company": company})


@login_required
@require_http_methods(["GET", "POST"])
def company_update_form(request, pk, **kwargs):
    return company_update(request, id=pk, **kwargs)
