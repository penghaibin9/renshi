from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

from base.auth_backends import company_scoped_active, get_allowed_company_ids
from base.context_processors import AllCompany
from base.middleware import CompanyMiddleware as LegacyCompanyMiddleware
from base.models import Company
from horilla.horilla_middlewares import get_selected_company, set_selected_company
from platform_access.services import (
    clear_elevation_session,
    get_active_tenant_elevation,
    is_platform_operator,
)


def _is_school_hr_path(path):
    return path.startswith(
        ("/hr/", "/api/v1/hr/", "/api/hr/v1/", "/payroll", "/offboarding", "/report")
    )


def _company_icon_url(company):
    icon = getattr(company, "icon", None)
    try:
        return icon.url if icon and getattr(icon, "name", None) else ""
    except ValueError:
        return ""


def _normalize_company_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _reset_to_all_scope(request):
    """Drop the tenant AND its display cache when access has been revoked."""
    if hasattr(request, "session"):
        request.session["selected_company"] = "all"
        request.session.pop("selected_company_instance", None)
        request.session.modified = True
    request.selected_company_instance = None
    request.write_company_id = None
    set_selected_company("all")


class SafeCompanyMiddleware(LegacyCompanyMiddleware):
    """A school account can exist before the first personnel record.

    Authentication and CompanyGroupAssignment establish school access. Creating
    an artificial Employee merely to get through middleware is not onboarding.
    The final elevation middleware still validates the concrete school.
    """

    def _get_user_default_company(self, request):
        if is_platform_operator(request.user):
            return None  # Never give operators an implicit school.
        allowed = get_allowed_company_ids(request.user)
        employee = getattr(request.user, "employee_get", None)
        work_info = getattr(employee, "employee_work_info", None)
        company = getattr(work_info, "company_id", None)
        if company is not None and company.pk in allowed:
            return company
        # Exactly one authorized school is unambiguous. Never use DB.first().
        if len(allowed) == 1:
            return Company.objects.filter(pk=next(iter(allowed))).first()
        return None

    def _set_company_session(self, request, company_id):
        operator = is_platform_operator(request.user)
        if company_id is not None:
            if not operator and company_id.pk not in get_allowed_company_ids(request.user):
                # Keep the requested ID for the final 403, but expose no foreign
                # school label. Do not silently retarget a write to another school.
                request.selected_company_instance = None
                request.session.pop("selected_company_instance", None)
                return None
            request.selected_company_instance = company_id
            request.session["selected_company"] = str(company_id.id)
            request.session["selected_company_instance"] = {
                "company": company_id.company,
                "icon": _company_icon_url(company_id),
                "text": "Platform tenant" if operator else "当前学校",
                "id": company_id.id,
            }
            return None

        request.selected_company_instance = None
        request.session["selected_company"] = "all"
        if operator:
            all_company = AllCompany()
            display = {"company": all_company.company, "icon": all_company.icon.url,
                       "text": all_company.text, "id": all_company.id}
        else:
            display = {"company": "我的学校", "icon": "", "text": "请选择学校", "id": "all"}
        request.session["selected_company_instance"] = display
        return None


class PlatformTenantElevationMiddleware:
    """Final tenant boundary, including historical school superusers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _school_bound_user(self, request, user, selected):
        request.write_company_id = None
        if selected in (None, "", "all"):
            return None
        normalized = _normalize_company_id(selected)
        if company_scoped_active():
            allowed = getattr(request, "allowed_company_ids", None)
            if allowed is None:
                allowed = get_allowed_company_ids(user)
            if normalized not in set(allowed or ()):
                _reset_to_all_scope(request)
                return JsonResponse(
                    {"detail": "The selected school is outside this account's tenant scope."},
                    status=403,
                )
        request.write_company_id = normalized
        return None

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            request.write_company_id = None
            if request.path_info.startswith("/hr/"):
                return redirect_to_login(request.get_full_path())
            return self.get_response(request)

        selected = get_selected_company()
        if not is_platform_operator(user):
            denied = self._school_bound_user(request, user, selected)
            return denied if denied is not None else self.get_response(request)

        request.write_company_id = None
        if selected in (None, "", "all"):
            clear_elevation_session(request)
            if selected == "all" and _is_school_hr_path(request.path_info):
                return JsonResponse(
                    {"detail": "Platform accounts must activate a time-boxed tenant "
                               "elevation before accessing school HR data."},
                    status=403,
                )
            return self.get_response(request)
        elevation = get_active_tenant_elevation(request, expected_company_id=selected)
        if elevation is None:
            _reset_to_all_scope(request)
            return JsonResponse(
                {"detail": "Active platform tenant elevation is required for this school."},
                status=403,
            )
        request.write_company_id = elevation.company_id
        return self.get_response(request)
