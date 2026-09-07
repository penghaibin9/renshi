"""HR03 staff account invitation administrator API."""

from __future__ import annotations

from django.urls import reverse
from django.views.decorators.http import require_POST

from hr_staff.account_contract import ACCOUNT_MANAGE_PERMISSION
from hr_staff.api.base import error_response, json_response, make_staff_context
from hr_staff.context import HrStaffContextError
from hr_staff.models import HrStaffMaster
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.selectors.staff_list import StaffListSelector
from hr_staff.services.account_invitation_service import (
    AccountInvitationError,
    AccountInvitationService,
    mask_email,
)


def _context_or_error(request):
    try:
        return make_staff_context(request), None
    except HrStaffContextError as exc:
        return None, error_response(
            request, exc.code, exc.message, status=getattr(exc, "status", 403)
        )


def _staff_in_scope(context, staff_id):
    selector = StaffListSelector(context)
    allowed = selector.apply_scope(selector.base_qs()).filter(id=staff_id).exists()
    if allowed:
        return True, None
    exists_in_tenant = HrStaffMaster.objects.filter(
        tenant_id=context.tenant_id, id=staff_id
    ).exists()
    return False, "STAFF_SCOPE_DENIED" if exists_in_tenant else "STAFF_NOT_FOUND"


def _service_error(request, exc: AccountInvitationError):
    if exc.code in {"STAFF_NOT_FOUND", "ACCOUNT_INVITATION_INVALID"}:
        status = 404
    elif exc.code in {
        "ACCOUNT_LINK_EXISTS",
        "ACCOUNT_INVITATION_ACCEPTED",
        "ACCOUNT_INVITATION_CONTACT_CHANGED",
        "ACCOUNT_SELF_ROLE_POLICY_INVALID",
    }:
        status = 409
    elif exc.code == "ACCOUNT_SELF_PERMISSION_MISSING":
        status = 503
    else:
        status = 400
    return error_response(request, exc.code, str(exc), status=status)


@require_POST
@require_hr_staff_permission(ACCOUNT_MANAGE_PERMISSION)
def issue_account_invitation(request, staff_id):
    context, error = _context_or_error(request)
    if error:
        return error

    allowed, denied_code = _staff_in_scope(context, staff_id)
    if not allowed:
        status = 403 if denied_code == "STAFF_SCOPE_DENIED" else 404
        message = (
            "当前数据范围无权为该教职工开通账号"
            if status == 403
            else "教职工不存在"
        )
        return error_response(request, denied_code, message, status=status)

    # Recipient email is authority-owned HR03 data. Do not accept an override
    # from the browser/API caller.
    if request.body and request.body.strip() not in {b"", b"{}"}:
        return error_response(
            request,
            "INVALID_REQUEST",
            "邀请收件邮箱来自已核验主档，禁止在请求中覆盖",
            status=400,
        )

    try:
        invitation, raw_token = AccountInvitationService(
            context.tenant_id, actor_user_id=request.user.id
        ).issue(staff_id=staff_id)
    except AccountInvitationError as exc:
        return _service_error(request, exc)

    # Keep the bearer secret in the URL fragment, not the request path/query.
    # Browsers never send fragments to reverse proxies/access logs. The public
    # page's external JS moves it into the POST body and erases the fragment.
    activation_url = request.build_absolute_uri(
        reverse(
            "account-invitation-activate",
            kwargs={"invitation_id": invitation.id},
        )
    )
    payload = {
        "schemaVersion": "hr03.account-invitation.1",
        "data": {
            "invitationId": str(invitation.id),
            "staffId": str(invitation.staff_id_id),
            "emailMasked": mask_email(invitation.invited_email),
            "expiresAt": invitation.expires_at.isoformat(),
            "deliveryMode": "MANUAL_LINK",
            "inviteUrl": f"{activation_url}#{raw_token}",
        },
    }
    return json_response(request, payload, status=201)


@require_POST
@require_hr_staff_permission(ACCOUNT_MANAGE_PERMISSION)
def revoke_account_invitation(request, invitation_id):
    context, error = _context_or_error(request)
    if error:
        return error
    try:
        invitation = AccountInvitationService(
            context.tenant_id, actor_user_id=request.user.id
        ).revoke(invitation_id=invitation_id)
    except AccountInvitationError as exc:
        return _service_error(request, exc)

    payload = {
        "schemaVersion": "hr03.account-invitation.1",
        "data": {
            "invitationId": str(invitation.id),
            "revoked": invitation.revoked_at is not None,
        },
    }
    return json_response(request, payload)
