"""Anonymous one-time account activation boundary for HR03 invitations."""

from __future__ import annotations

from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from hr_staff.services.account_invitation_service import (
    AccountInvitationError,
    AccountInvitationService,
)


def _render(request, *, status=200, errors=None):
    errors = errors or {}
    response = render(
        request,
        "base/account/invitation_activate.html",
        {
            "errors": errors,
            "non_field_error": errors.get("__all__", ""),
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@sensitive_post_parameters("activation_token", "password", "confirm_password")
@never_cache
@require_http_methods(["GET", "POST"])
def activate_account_invitation(request, invitation_id):
    # Never allow a currently authenticated browser to accidentally consume an
    # invitation and create a second identity under someone else's session.
    if getattr(request.user, "is_authenticated", False):
        return _render(
            request,
            status=409,
            errors={"__all__": "请先退出当前登录账号，再打开教职工账号邀请链接。"},
        )

    if request.method == "GET":
        # The bearer secret lives only in the URL fragment. Fragments are not
        # sent in HTTP requests, so reverse proxies/access logs see only this
        # non-secret invitation UUID. Browser JS moves the fragment into the
        # POST body and immediately removes it from the address bar/history.
        return _render(request)

    raw_token = str(request.POST.get("activation_token") or "")
    username = str(request.POST.get("username") or "").strip()
    password = str(request.POST.get("password") or "")
    confirm_password = str(request.POST.get("confirm_password") or "")
    errors = {}
    if not raw_token:
        errors["__all__"] = "邀请密钥缺失，请使用学校管理员提供的完整邀请链接。"
    if not username:
        errors["username"] = "请输入登录账号。"
    if not password:
        errors["password"] = "请输入密码。"
    if password != confirm_password:
        errors["confirm_password"] = "两次输入的密码不一致。"
    if errors:
        return _render(request, status=400, errors=errors)

    try:
        invitation = AccountInvitationService.inspect(raw_token)
        if invitation.id != invitation_id:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_INVALID", "邀请链接与密钥不匹配"
            )
        user, _link = AccountInvitationService.accept(
            raw_token, username=username, password=password
        )
    except AccountInvitationError as exc:
        field = "__all__"
        if exc.code.startswith("ACCOUNT_USERNAME_"):
            field = "username"
        elif exc.code == "ACCOUNT_PASSWORD_INVALID":
            field = "password"
        message = (
            "邀请链接已失效，请联系学校管理员重新签发。"
            if exc.code
            in {
                "ACCOUNT_INVITATION_INVALID",
                "ACCOUNT_INVITATION_EXPIRED",
                "ACCOUNT_INVITATION_REVOKED",
                "ACCOUNT_INVITATION_ACCEPTED",
            }
            else str(exc)
        )
        return _render(request, status=400, errors={field: message})

    # Do not authenticate here: possession of the invitation must not become a
    # long-lived browser session. The user proves the new credential at login.
    request.session["account_activation_complete"] = {"username": user.username}
    request.session.modified = True
    return redirect("account-invitation-complete")


@never_cache
@require_GET
def account_invitation_complete(request):
    data = request.session.pop("account_activation_complete", None)
    if not data:
        return redirect("login")
    response = render(
        request,
        "base/account/invitation_complete.html",
        {"username": data.get("username", "")},
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
