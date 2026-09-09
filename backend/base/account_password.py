"""Account-owned password change; no optional Employee or HR03 record required."""
from auditlog.models import LogEntry
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from base.account_views import _require_account, account_can_sign_in
from base.forms import ChangePasswordForm
from platform_access.services import clear_elevation_session


class AccountPasswordForm(ChangePasswordForm):
    """Preserve established field names while applying configured validators."""
    def clean_new_password(self):
        value = super().clean_new_password()
        validate_password(value, self.user)
        return value


@sensitive_post_parameters("old_password", "new_password", "confirm_password")
@never_cache
@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def change_password(request):
    _require_account(request)
    form = AccountPasswordForm(user=request.user)
    status = 200
    if request.method == "POST":
        # Revalidate against the locked current account: a concurrent change
        # cannot accept an old password from this request's stale User object.
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if not account_can_sign_in(user):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied
            form = AccountPasswordForm(user, request.POST)
            if form.is_valid():
                first_change = bool(user.is_new_employee)
                user.set_password(form.cleaned_data["new_password"])
                user.is_new_employee = False
                user.save(update_fields=["password", "is_new_employee"])
                # Never write password values, hashes, session IDs or CSRF
                # tokens into the audit. Audit failure rolls back both fields.
                LogEntry.objects.log_create(
                    user, actor=user, action=LogEntry.Action.UPDATE,
                    changes={"password": ["[REDACTED]", "[REDACTED]"],
                             "is_new_employee": [first_change, False]},
                    serialized_data=None,
                    additional_data={"source": "account_password",
                                     "first_change": first_change},
                )
            else:
                status = 400
        if status == 200:
            # Preserve this session through Django's standard auth-hash update
            # and session-key rotation; other old sessions become invalid.
            update_session_auth_hash(request, user)
            clear_elevation_session(request)
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("home-page")
                return response
            return redirect("home-page")
    return render(request, "base/account/password_change.html", {
        "form": form, "first_change": bool(request.user.is_new_employee),
    }, status=status)
