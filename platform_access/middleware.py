from django.http import JsonResponse

from base.context_processors import AllCompany
from base.middleware import CompanyMiddleware as LegacyCompanyMiddleware
from horilla.horilla_middlewares import get_selected_company, set_selected_company
from platform_access.services import (
    clear_elevation_session,
    get_active_tenant_elevation,
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


class SafeCompanyMiddleware(LegacyCompanyMiddleware):
    """Preserve school-user behavior while supporting platform-only accounts."""

    def _set_company_session(self, request, company_id):
        user = getattr(request, "user", None)
        if not (
            user
            and getattr(user, "is_authenticated", False)
            and getattr(user, "is_superuser", False)
        ):
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
    """Require an audited time-boxed grant before platform users enter a school."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not (
            user
            and getattr(user, "is_authenticated", False)
            and getattr(user, "is_superuser", False)
        ):
            return self.get_response(request)

        selected = get_selected_company()
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
            request.session["selected_company"] = "all"
            request.session.modified = True
            set_selected_company("all")
            return JsonResponse(
                {
                    "detail": (
                        "Active platform tenant elevation is required for this school."
                    )
                },
                status=403,
            )

        return self.get_response(request)
