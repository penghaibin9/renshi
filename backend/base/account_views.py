"""Account entry points independent of optional personnel records.

These callbacks own the public routes in account_urls. Employee-only legacy
business views retain their stricter decorator; school grants never create an
Employee, a staff master, an organization, or a platform elevation.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from base.auth_backends import get_assigned_company_ids
from platform_access.services import clear_elevation_session, is_platform_operator


def account_can_sign_in(user):
    """An active Employee OR an explicit school membership OR a platform account."""
    if not user or not user.is_active:
        return False
    employee = getattr(user, "employee_get", None)
    if employee is not None:
        # A school grant must not resurrect an archived personnel identity.
        return bool(employee.is_active)
    return bool(get_assigned_company_ids(user)) or is_platform_operator(user)


def _require_account(request):
    if not account_can_sign_in(request.user):
        raise PermissionDenied(_("This account has no active school access."))


def _next_url(request):
    target = request.GET.get("next") or request.POST.get("next") or reverse("home-page")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = reverse("home-page")
    parts = urlsplit(target)
    extra = [(key, value) for key, values in request.GET.lists()
             if key != "next" for value in values]
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True) + extra)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


@never_cache
@require_http_methods(["GET", "POST"])
def login_user(request):
    if request.method == "GET":
        return render(request, "login.html", {
            # Initial platform credentials are a deployment operation. The
            # legacy HTTP installer is retired, including its public children.
            "initialize_database": False,
        })

    user = authenticate(request, username=request.POST.get("username"),
                        password=request.POST.get("password"))
    if not user or not account_can_sign_in(user):
        messages.error(request, _("Invalid credentials or inactive account access."))
        return redirect("login")

    # Keep the existing remember-me policy and Django authentication signals.
    from base.views import _configure_login_session

    login(request, user)
    _configure_login_session(request, request.POST.get("remember_me") == "on")
    # login() can retain the same user's session. Do not carry an old tenant
    # selection or a support elevation into a fresh authentication.
    request.session.pop("selected_company", None)
    request.session.pop("selected_company_instance", None)
    clear_elevation_session(request)
    messages.success(request, _("Login successful."))
    return redirect(_next_url(request))


@never_cache
@login_required(login_url="login")
@require_safe
def home(request):
    _require_account(request)
    if getattr(request.user, "employee_get", None) is not None:
        return redirect("dashboard")
    if is_platform_operator(request.user):
        return redirect("admin:index")
    # New-school teachers may have a canonical HR03 account link without an
    # Employee. Their ordinary landing must not be an admin-only settings page.
    # This is navigation only: HR17 still checks membership, permission and
    # the explicit identity. Administrators retain the school-center landing.
    if request.user.has_perm("hr.self.view") and not request.user.has_perm("base.view_company"):
        return redirect("hr_self:overview")
    # SafeCompanyMiddleware selects only an unambiguous authorized school.
    # With multiple schools, settings remains fail-closed until one is chosen.
    return redirect("school-management")


@never_cache
@login_required(login_url="login")
@require_safe
def notifications(request):
    """The header's initial HTMX read is account-owned, not Employee-owned."""
    _require_account(request)
    return render(request, "notification/notification_items.html", {
        "notifications": request.user.notifications.unread(),
    })


@never_cache
@login_required(login_url="login")
@require_safe
def all_notifications(request):
    _require_account(request)
    return render(request, "notification/all_notifications.html", {
        "notifications": request.user.notifications.all(),
    })


@never_cache
@login_required(login_url="login")
@require_safe
def get_horilla_installed_apps(request):
    """Return the shared asset manifest to an admitted account, not an Employee.

    HTMX consumes a JSON array from this URL after each swap. The old
    personnel-only decorator returned an HTML login script to first-school
    accounts, leaving installed_apps undefined in the Select2 loader. This is
    asset discovery only: listing an app never grants its business permissions.
    """
    _require_account(request)
    return JsonResponse({"installed_apps": list(settings.APPS)})
