"""Controlled HR03 staff -> login account invitation lifecycle.

Security invariants:
- only verified, currently-valid HR03 email facts can receive an invitation;
- raw bearer tokens are never persisted or audited;
- a stored digest is rejected if presented as a bearer token;
- reissue revokes every previous unconsumed invitation for the staff identity;
- acceptance, user creation, tenant role assignment, HrAccountLink and audit are atomic;
- an existing account-link history is never silently replaced by a new account.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from base.models import Company, CompanyGroupAssignment
from base.token_security import TOKEN_DIGEST_PREFIX, bearer_token_digest
from hr_staff.account_contract import (
    INVITATION_TOKEN_NAMESPACE,
    INVITATION_TTL_HOURS,
    SELF_PERMISSION,
    SYSTEM_SELF_GROUP,
)
from hr_staff.models import (
    HrAccountInvitation,
    HrAccountLink,
    HrPersonContact,
    HrStaffMaster,
)
from hr_staff.services.audit_service import write_audit_event


class AccountInvitationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def mask_email(value: str) -> str:
    local, sep, domain = (value or "").partition("@")
    if not sep or not local or not domain:
        return "***"
    if len(local) == 1:
        masked = local + "***"
    elif len(local) == 2:
        masked = local[0] + "*" + local[-1]
    else:
        masked = local[0] + "*" * min(6, len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


class AccountInvitationService:
    def __init__(self, tenant_id: int, *, actor_user_id: int | None = None):
        if not tenant_id:
            raise AccountInvitationError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _digest_raw_token(raw_token: str) -> str:
        value = str(raw_token or "")
        # bearer_token_digest() is deliberately idempotent for storage migration.
        # At this authentication boundary a digest itself must NEVER be accepted
        # as a bearer credential if a database/read log ever leaks it.
        if (
            len(value) < 40
            or len(value) > 256
            or value.startswith(TOKEN_DIGEST_PREFIX)
        ):
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_INVALID", "邀请链接无效或已失效"
            )
        return bearer_token_digest(value, namespace=INVITATION_TOKEN_NAMESPACE)

    @staticmethod
    def _verified_email(staff: HrStaffMaster) -> str:
        today = timezone.localdate()
        contacts = list(
            HrPersonContact.objects.filter(
                tenant_id=staff.tenant_id,
                person_id=staff.person_id_id,
                contact_kind__in=("WORK_EMAIL", "PERSONAL_EMAIL"),
                is_verified=True,
            )
            .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
            .order_by("-is_primary", "created_at", "id")
        )
        contacts.sort(
            key=lambda row: (
                0 if row.contact_kind == "WORK_EMAIL" else 1,
                0 if row.is_primary else 1,
                row.created_at,
                str(row.id),
            )
        )
        User = get_user_model()
        for contact in contacts:
            value = str(contact.contact_value or "").strip()
            try:
                validate_email(value)
            except ValidationError:
                continue
            return User.objects.normalize_email(value).casefold()
        raise AccountInvitationError(
            "ACCOUNT_INVITATION_EMAIL_REQUIRED",
            "该教职工没有已核验且当前有效的邮箱，请先维护主档联系方式",
        )

    @staticmethod
    def _usable(invitation: HrAccountInvitation, now=None):
        now = now or timezone.now()
        if invitation.accepted_at is not None:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_ACCEPTED", "邀请已使用"
            )
        if invitation.revoked_at is not None:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_REVOKED", "邀请已撤销"
            )
        if invitation.expires_at <= now:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_EXPIRED", "邀请已过期"
            )

    def issue(self, *, staff_id):
        now = timezone.now()
        with transaction.atomic():
            staff = (
                HrStaffMaster.objects.select_for_update()
                .select_related("person_id")
                .filter(tenant_id=self.tenant_id, id=staff_id)
                .first()
            )
            if staff is None:
                raise AccountInvitationError("STAFF_NOT_FOUND", "教职工不存在")
            if HrAccountLink.objects.select_for_update().filter(
                tenant_id=self.tenant_id, staff_id=staff.id
            ).exists():
                raise AccountInvitationError(
                    "ACCOUNT_LINK_EXISTS",
                    "该教职工已有账号关联历史，禁止通过新邀请静默替换",
                )
            invited_email = self._verified_email(staff)

            HrAccountInvitation.objects.select_for_update().filter(
                tenant_id=self.tenant_id,
                staff_id=staff.id,
                accepted_at__isnull=True,
                revoked_at__isnull=True,
            ).update(revoked_at=now)

            raw_token = secrets.token_urlsafe(48)
            invitation = HrAccountInvitation.objects.create(
                tenant_id=self.tenant_id,
                staff_id=staff,
                invited_email=invited_email,
                token_digest=self._digest_raw_token(raw_token),
                expires_at=now + timedelta(hours=INVITATION_TTL_HOURS),
                created_by_user_id=self.actor_user_id,
            )
            write_audit_event(
                tenant_id=self.tenant_id,
                staff_id=staff.id,
                person_id=staff.person_id_id,
                actor_user_id=self.actor_user_id,
                action="StaffAccountInvitationIssued",
                business_type="HR_ACCOUNT_INVITATION",
                business_id=str(invitation.id),
                reason=(
                    f"expires_at={invitation.expires_at.isoformat()};"
                    "delivery=manual_link"
                ),
                source="hr_staff.account_invitation",
            )
        return invitation, raw_token

    def revoke(self, *, invitation_id):
        now = timezone.now()
        with transaction.atomic():
            invitation = (
                HrAccountInvitation.objects.select_for_update()
                .select_related("staff_id")
                .filter(tenant_id=self.tenant_id, id=invitation_id)
                .first()
            )
            if invitation is None:
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_INVALID", "邀请不存在"
                )
            if invitation.accepted_at is not None:
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_ACCEPTED", "已使用邀请不能撤销"
                )
            if invitation.revoked_at is None:
                invitation.revoked_at = now
                invitation.save(update_fields=["revoked_at", "updated_at"])
                write_audit_event(
                    tenant_id=self.tenant_id,
                    staff_id=invitation.staff_id_id,
                    actor_user_id=self.actor_user_id,
                    action="StaffAccountInvitationRevoked",
                    business_type="HR_ACCOUNT_INVITATION",
                    business_id=str(invitation.id),
                    reason="manual_revoke",
                    source="hr_staff.account_invitation",
                )
        return invitation

    @classmethod
    def inspect(cls, raw_token: str) -> HrAccountInvitation:
        digest = cls._digest_raw_token(raw_token)
        invitation = (
            HrAccountInvitation.objects.select_related(
                "staff_id", "staff_id__person_id"
            )
            .filter(token_digest=digest)
            .first()
        )
        if invitation is None:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_INVALID", "邀请链接无效或已失效"
            )
        cls._usable(invitation)
        return invitation

    @classmethod
    def _self_group(cls):
        permission = (
            Permission.objects.filter(
                content_type__app_label="hr_self", codename=SELF_PERMISSION
            )
            .order_by("id")
            .first()
        )
        if permission is None:
            raise AccountInvitationError(
                "ACCOUNT_SELF_PERMISSION_MISSING",
                "本人服务权限尚未完成数据库物化，禁止创建半成品账号",
            )

        group = Group.objects.select_for_update().filter(name=SYSTEM_SELF_GROUP).first()
        if group is None:
            # The group name is globally unique. A concurrent first activation
            # may win the insert after our empty lookup, so isolate the insert
            # in a savepoint and then lock the winner instead of leaking a DB
            # IntegrityError or leaving the outer acceptance transaction broken.
            try:
                with transaction.atomic():
                    group = Group.objects.create(name=SYSTEM_SELF_GROUP)
            except IntegrityError:
                group = Group.objects.select_for_update().get(name=SYSTEM_SELF_GROUP)

        permission_ids = set(group.permissions.values_list("id", flat=True))
        extra = permission_ids - {permission.id}
        if extra:
            raise AccountInvitationError(
                "ACCOUNT_SELF_ROLE_POLICY_INVALID",
                "系统本人服务角色包含额外权限，已拒绝自动授予",
            )
        if permission.id not in permission_ids:
            group.permissions.add(permission)
        return group

    @classmethod
    def accept(cls, raw_token: str, *, username: str, password: str):
        digest = cls._digest_raw_token(raw_token)
        username = str(username or "").strip()
        if not username:
            raise AccountInvitationError(
                "ACCOUNT_USERNAME_REQUIRED", "请输入登录账号"
            )
        User = get_user_model()
        username_max_length = User._meta.get_field("username").max_length or 150
        if len(username) > username_max_length:
            raise AccountInvitationError(
                "ACCOUNT_USERNAME_INVALID",
                f"登录账号不能超过 {username_max_length} 个字符",
            )
        try:
            UnicodeUsernameValidator()(username)
        except ValidationError as exc:
            raise AccountInvitationError(
                "ACCOUNT_USERNAME_INVALID", "登录账号包含不允许的字符"
            ) from exc

        # Resolve only the lock key first. The transaction acquires locks in
        # the same order as issue(): staff first, invitation second. The token
        # state is revalidated after both locks are held.
        probe = HrAccountInvitation.objects.filter(token_digest=digest).values(
            "tenant_id", "staff_id_id"
        ).first()
        if probe is None:
            raise AccountInvitationError(
                "ACCOUNT_INVITATION_INVALID", "邀请链接无效或已失效"
            )

        with transaction.atomic():
            staff = (
                HrStaffMaster.objects.select_for_update()
                .select_related("person_id")
                .filter(
                    tenant_id=probe["tenant_id"],
                    id=probe["staff_id_id"],
                )
                .first()
            )
            invitation = (
                HrAccountInvitation.objects.select_for_update()
                .filter(token_digest=digest)
                .first()
            )
            if staff is None or invitation is None:
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_INVALID", "邀请链接无效或已失效"
                )
            cls._usable(invitation)

            if (
                invitation.staff_id_id != staff.id
                or staff.tenant_id != invitation.tenant_id
                or staff.person_id.tenant_id != invitation.tenant_id
            ):
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_INVALID", "邀请与人员主档的学校边界不一致"
                )
            current_email = cls._verified_email(staff)
            if current_email.casefold() != invitation.invited_email.casefold():
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_CONTACT_CHANGED",
                    "主档邮箱已变化，请由学校管理员重新签发邀请",
                )
            if HrAccountLink.objects.select_for_update().filter(
                tenant_id=invitation.tenant_id, staff_id=staff.id
            ).exists():
                raise AccountInvitationError(
                    "ACCOUNT_LINK_EXISTS", "该教职工已存在账号关联"
                )
            if User.objects.filter(username__iexact=username).exists():
                raise AccountInvitationError(
                    "ACCOUNT_USERNAME_TAKEN", "该登录账号已被使用"
                )

            candidate = User(
                username=username,
                email=invitation.invited_email,
                first_name=str(staff.person_id.legal_name or "")[:150],
                is_active=True,
                is_new_employee=False,
            )
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                message = "；".join(str(item) for item in exc.messages)
                raise AccountInvitationError(
                    "ACCOUNT_PASSWORD_INVALID", message or "密码不符合安全策略"
                ) from exc

            # create_user hashes the password; password/token values never enter audit.
            # Keep the unique-key race inside a savepoint so a concurrent winner
            # becomes a stable business conflict and the outer transaction remains
            # usable for rollback/cleanup.
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        email=invitation.invited_email,
                        password=password,
                        first_name=candidate.first_name,
                        is_active=True,
                        is_new_employee=False,
                    )
            except IntegrityError as exc:
                raise AccountInvitationError(
                    "ACCOUNT_USERNAME_TAKEN", "该登录账号已被使用"
                ) from exc

            group = cls._self_group()
            company = (
                Company.objects.select_for_update()
                .filter(pk=invitation.tenant_id)
                .first()
            )
            if company is None:
                raise AccountInvitationError(
                    "ACCOUNT_INVITATION_INVALID", "邀请对应学校不存在"
                )
            CompanyGroupAssignment.objects.get_or_create(
                user=user, company=company, group=group
            )
            CompanyGroupAssignment.sync_user_group_membership(user, group)

            now = timezone.now()
            link = HrAccountLink.objects.create(
                tenant_id=invitation.tenant_id,
                staff_id=staff,
                auth_user_id=user.id,
                auth_identifier=user.username,
                link_status=HrAccountLink.LinkStatus.ACTIVE,
                linked_at=now,
            )
            invitation.accepted_at = now
            invitation.accepted_user_id = user.id
            invitation.save(
                update_fields=["accepted_at", "accepted_user_id", "updated_at"]
            )
            write_audit_event(
                tenant_id=invitation.tenant_id,
                staff_id=staff.id,
                person_id=staff.person_id_id,
                actor_user_id=user.id,
                action="StaffAccountInvitationAccepted",
                business_type="HR_ACCOUNT_INVITATION",
                business_id=str(invitation.id),
                after_snapshot_ref=f"hr-account-link:{link.id}",
                reason="password_established;session_not_created",
                source="hr_staff.account_invitation",
            )
        return user, link
