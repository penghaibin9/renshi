"""Anonymous one-time account activation boundary for HR03 invitations."""

from __future__ import annotations

from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET

from hr_staff.services.account_invitation_service import (
    AccountInvitationError,
    AccountInvitationService,
    mask_email,
)


def _render(request, *, status=200, invitation=None, errors=None):
    response = render(
        request,
        "base/account/invitation_activate.html",
        {
            "invitation": invitation,
            "email_masked": mask_email(invitation.invited_email)
            if invitation
            else "",
            "errors": errors or {},
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@sensitive_post_parameters("password", "confirm_password")
@never_cache
@require_http_methods(["GET", "POST"])
def activate_account_invitation(request, token):
    # Never allow a currently authenticated browser to accidentally consume an
    # invitation and create a second identity under someone else's session.
    if getattr(request.user, "is_authenticated", False):
        return _render(
            request,
            status=409,
            errors={"__all__": "请先退出当前登录账号，再打开教职工账号邀请链接。"},
        )

    try:
        invitation = AccountInvitationService.inspect(token)
    except AccountInvitationError:
        return _render(
            request,
            status=400,
            errors={"__all__": "邀请链接无效、已撤销、已使用或已经过期，请联系学校管理员重新签发。"},
        )

    if request.method == "GET":
        return _render(request, invitation=invitation)

    username = str(request.POST.get("username") or "").strip()
    password = str(request.POST.get("password") or "")
    confirm_password = str(request.POST.get("confirm_password") or "")
    errors = {}
    if not username:
        errors["username"] = "请输入登录账号。"
    if not password:
        errors["password"] = "请输入密码。"
    if password != confirm_password:
        errors["confirm_password"] = "两次输入的密码不一致。"
    if errors:
        return _render(
            request, status=400, invitation=invitation, errors=errors
        )

    try:
        user, _link = AccountInvitationService.accept(
            token, username=username, password=password
        )
    except AccountInvitationError as exc:
        field = "__all__"
        if exc.code.startswith("ACCOUNT_USERNAME_"):
            field = "username"
        elif exc.code == "ACCOUNT_PASSWORD_INVALID":
            field = "password"
        elif exc.code in {
            "ACCOUNT_INVITATION_CONTACT_CHANGED",
            "ACCOUNT_LINK_EXISTS",
        }:
            field = "__all__"
        # Token state details are intentionally collapsed for the browser.
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
        return _render(
            request,
            status=400,
            invitation=invitation,
            errors={field: message},
        )

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
