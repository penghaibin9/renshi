from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

from base.auth_backends import company_scoped_active, get_allowed_company_ids
from base.context_processors import AllCompany
from base.middleware import CompanyMiddleware as LegacyCompanyMiddleware
from horilla.horilla_middlewares import get_selected_company, set_selected_company
from platform_access.services import (
    clear_elevation_session,
    get_active_tenant_elevation,
    is_platform_operator,
)


def _is_school_hr_path(path):
    return path.startswith(
        (
            "/hr/",
            "/api/v1/hr/",
            "/api/hr/v1/",
            "/payroll",
            "/offboarding",
            "/report",
        )
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
    """Drop any concrete tenant from both session and execution context."""
    if hasattr(request, "session"):
        request.session["selected_company"] = "all"
        request.session.modified = True
    request.write_company_id = None
    set_selected_company("all")


class SafeCompanyMiddleware(LegacyCompanyMiddleware):
    """Preserve school-user behavior while supporting platform-only accounts."""

    def _set_company_session(self, request, company_id):
        user = getattr(request, "user", None)
        if not is_platform_operator(user):
            return super()._set_company_session(request, company_id)

        if company_id is not None:
            request.selected_company_instance = company_id
            request.session["selected_company"] = str(company_id.id)
            request.session["selected_company_instance"] = {
                "company": company_id.company,
                "icon": _company_icon_url(company_id),
                "text": "Platform tenant",
                "id": company_id.id,
            }
            return None

        request.selected_company_instance = None
        request.session["selected_company"] = "all"
        all_company = AllCompany()
        request.session["selected_company_instance"] = {
            "company": all_company.company,
            "icon": all_company.icon.url,
            "text": all_company.text,
            "id": all_company.id,
        }
        return None


class PlatformTenantElevationMiddleware:
    """Enforce the final tenant boundary after legacy company resolution.

    There are two distinct privileged identities in this codebase:
    - school-bound administrators may legitimately have ``is_superuser=True``
      but still belong only to their assigned/work-info schools;
    - platform-only superusers have no Employee identity and may enter one school
      only through an audited, time-boxed elevation.

    CompanyMiddleware historically exempted every superuser from tenant clamping.
    This final boundary therefore re-validates concrete school membership for all
    school-bound users, including school superusers, before any downstream view
    executes.  It also canonicalizes ``request.write_company_id`` *after* the
    current ContextVar has been resolved so an ``all`` request can never inherit
    a write tenant from a previous request context.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _school_bound_user(self, request, user, selected):
        # Union/all and missing tenant are always read-only at this boundary.
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
                    {
                        "detail": (
                            "The selected school is outside this account's tenant scope."
                        )
                    },
                    status=403,
                )

        # A concrete, authorized tenant is the only valid implicit web write scope.
        request.write_company_id = normalized
        return None

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            request.write_company_id = None
            # HR workspaces render the shared authenticated shell.  Letting an
            # anonymous request reach those views used to produce a large 403
            # page whose shell scripts repeatedly reloaded the same URL.  UI
            # entries should follow Django's normal sign-in flow; APIs retain
            # their existing JSON fail-closed responses.
            if request.path_info.startswith("/hr/"):
                return redirect_to_login(request.get_full_path())
            return self.get_response(request)

        selected = get_selected_company()
        if not is_platform_operator(user):
            denied = self._school_bound_user(request, user, selected)
            return denied if denied is not None else self.get_response(request)

        # Platform-only identities never receive an implicit tenant write scope.
        request.write_company_id = None
        if selected in (None, "", "all"):
            clear_elevation_session(request)
            if selected == "all" and _is_school_hr_path(request.path_info):
                return JsonResponse(
                    {
                        "detail": (
                            "Platform accounts must activate a time-boxed tenant "
                            "elevation before accessing school HR data."
                        )
                    },
                    status=403,
                )
            return self.get_response(request)

        elevation = get_active_tenant_elevation(
            request, expected_company_id=selected
        )
        if elevation is None:
            _reset_to_all_scope(request)
            return JsonResponse(
                {
                    "detail": (
                        "Active platform tenant elevation is required for this school."
                    )
                },
                status=403,
            )

        request.write_company_id = elevation.company_id
        return self.get_response(request)
