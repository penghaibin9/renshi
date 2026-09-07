"""Production contracts for HR03 staff account invitation and activation."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from base.models import Company, CompanyGroupAssignment
from hr_self.services.identity_service import SelfIdentityService
from hr_staff.api import account_invitations as account_api
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import (
    HrAccountInvitation,
    HrAccountLink,
    HrPerson,
    HrPersonContact,
    HrStaffAuditEvent,
    HrStaffMaster,
)
from hr_staff.services.account_invitation_service import (
    AccountInvitationError,
    AccountInvitationService,
)


User = get_user_model()


@override_settings(
    COMPANY_SCOPED_PERMISSIONS=True,
    TENANT_FAIL_CLOSED=True,
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
)
class AccountInvitationTests(TestCase):
    password = "Invite-Password-Contract-7429"

    def setUp(self):
        self.company = Company.objects.create(
            company="Account Invite School",
            address="",
            country="CN",
            state="",
            city="",
            zip="",
        )
        self.other_company = Company.objects.create(
            company="Other Invite School",
            address="",
            country="CN",
            state="",
            city="",
            zip="",
        )
        self.admin = User.objects.create_superuser(
            username="invite-root", email="", password="Admin-Password-Contract-8251"
        )
        self.person = HrPerson.objects.create(
            tenant_id=self.company.id,
            legal_name="邀请测试教师",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.id,
            person_id=self.person,
            staff_no="INVITE-001",
            current_employment_status="ACTIVE",
        )
        self.contact = HrPersonContact.objects.create(
            tenant_id=self.company.id,
            person_id=self.person,
            contact_kind=HrPersonContact.ContactKind.WORK_EMAIL,
            contact_value="Teacher.Invite@example.edu.cn",
            masked_display="T***@example.edu.cn",
            is_primary=True,
            is_verified=True,
        )

    def issue(self):
        return AccountInvitationService(
            self.company.id, actor_user_id=self.admin.id
        ).issue(staff_id=self.staff.id)

    def test_issue_persists_only_digest_and_reissue_revokes_old_token(self):
        first, first_token = self.issue()
        self.assertTrue(first.token_digest.startswith("sha256$"))
        self.assertNotIn(first_token, first.token_digest)
        self.assertNotEqual(first_token, first.token_digest)

        # A stolen database digest is not itself a bearer credential.
        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.inspect(first.token_digest)
        self.assertEqual(caught.exception.code, "ACCOUNT_INVITATION_INVALID")

        second, second_token = self.issue()
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNone(second.revoked_at)
        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.inspect(first_token)
        self.assertEqual(caught.exception.code, "ACCOUNT_INVITATION_REVOKED")
        self.assertEqual(AccountInvitationService.inspect(second_token).id, second.id)

        audits = HrStaffAuditEvent.objects.filter(
            action="StaffAccountInvitationIssued"
        )
        self.assertEqual(audits.count(), 2)
        for audit in audits:
            rendered = (
                f"{audit.reason} {audit.before_snapshot_ref} "
                f"{audit.after_snapshot_ref}"
            )
            self.assertNotIn(first_token, rendered)
            self.assertNotIn(second_token, rendered)

    def test_accept_is_atomic_links_self_identity_and_replay_fails(self):
        invitation, token = self.issue()
        user, link = AccountInvitationService.accept(
            token, username="teacher-invite-001", password=self.password
        )

        invitation.refresh_from_db()
        self.assertEqual(invitation.accepted_user_id, user.id)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertFalse(user.is_new_employee)
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(link.auth_user_id, user.id)
        self.assertEqual(link.link_status, HrAccountLink.LinkStatus.ACTIVE)

        assignment = CompanyGroupAssignment.objects.get(
            user=user, company=self.company
        )
        permission_codes = set(
            assignment.group.permissions.values_list("codename", flat=True)
        )
        self.assertEqual(permission_codes, {"hr.self.view"})
        self.assertEqual(
            SelfIdentityService(self.company.id).resolve(user).staff_id, self.staff.id
        )

        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.accept(
                token, username="replay-user", password=self.password
            )
        self.assertEqual(caught.exception.code, "ACCOUNT_INVITATION_ACCEPTED")
        self.assertFalse(User.objects.filter(username="replay-user").exists())
        self.assertEqual(
            HrStaffAuditEvent.objects.filter(
                action="StaffAccountInvitationAccepted"
            ).count(),
            1,
        )

    def test_verified_current_email_is_required_and_contact_change_invalidates_token(
        self,
    ):
        self.contact.is_verified = False
        self.contact.save(update_fields=["is_verified"])
        with self.assertRaises(AccountInvitationError) as caught:
            self.issue()
        self.assertEqual(
            caught.exception.code, "ACCOUNT_INVITATION_EMAIL_REQUIRED"
        )
        self.assertFalse(HrAccountInvitation.objects.exists())

        self.contact.is_verified = True
        self.contact.save(update_fields=["is_verified"])
        invitation, token = self.issue()
        self.contact.contact_value = "new-address@example.edu.cn"
        self.contact.save(update_fields=["contact_value"])

        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.accept(
                token, username="teacher-contact-change", password=self.password
            )
        self.assertEqual(
            caught.exception.code, "ACCOUNT_INVITATION_CONTACT_CHANGED"
        )
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        self.assertFalse(
            User.objects.filter(username="teacher-contact-change").exists()
        )

    def test_expired_revoked_and_cross_tenant_paths_fail_closed(self):
        invitation, token = self.issue()
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.inspect(token)
        self.assertEqual(caught.exception.code, "ACCOUNT_INVITATION_EXPIRED")

        other_person = HrPerson.objects.create(
            tenant_id=self.other_company.id,
            legal_name="其他学校教师",
            status="ACTIVE",
        )
        other_staff = HrStaffMaster.objects.create(
            tenant_id=self.other_company.id,
            person_id=other_person,
            staff_no="OTHER-001",
        )
        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService(self.company.id).issue(
                staff_id=other_staff.id
            )
        self.assertEqual(caught.exception.code, "STAFF_NOT_FOUND")

    def test_existing_link_or_polluted_system_self_role_blocks_new_account(self):
        existing = User.objects.create_user(
            username="already-linked", password=self.password
        )
        HrAccountLink.objects.create(
            tenant_id=self.company.id,
            staff_id=self.staff,
            auth_user_id=existing.id,
            auth_identifier=existing.username,
            link_status=HrAccountLink.LinkStatus.UNLINKED,
        )
        with self.assertRaises(AccountInvitationError) as caught:
            self.issue()
        self.assertEqual(caught.exception.code, "ACCOUNT_LINK_EXISTS")

        HrAccountLink.objects.all().delete()
        _invite, token = self.issue()
        self_perm = Permission.objects.get(
            content_type__app_label="hr_self", codename="hr.self.view"
        )
        extra_perm = Permission.objects.exclude(pk=self_perm.pk).first()
        self.assertIsNotNone(extra_perm)
        group, _ = Group.objects.get_or_create(name="__system_hr17_self__")
        group.permissions.set([self_perm, extra_perm])

        with self.assertRaises(AccountInvitationError) as caught:
            AccountInvitationService.accept(
                token, username="must-not-exist", password=self.password
            )
        self.assertEqual(
            caught.exception.code, "ACCOUNT_SELF_ROLE_POLICY_INVALID"
        )
        self.assertFalse(User.objects.filter(username="must-not-exist").exists())
        self.assertFalse(
            HrAccountLink.objects.filter(
                tenant_id=self.company.id, staff_id=self.staff
            ).exists()
        )

    def test_admin_api_uses_staff_scope_and_never_accepts_recipient_override(self):
        request_factory = RequestFactory()
        context = HrStaffRequestContext(
            tenant_id=self.company.id,
            scope=HrStaffScope(scope_type="SCHOOL"),
        )
        request = request_factory.post(
            f"/api/v1/hr/staff/{self.staff.id}/account-invitations",
            data=b"{}",
            content_type="application/json",
        )
        request.user = self.admin
        with mock.patch(
            "hr_staff.api.account_invitations.make_staff_context",
            return_value=context,
        ):
            response = account_api.issue_account_invitation(
                request, self.staff.id
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["deliveryMode"], "MANUAL_LINK")
        self.assertIn("/activate-account/", data["inviteUrl"])
        self.assertNotIn(self.contact.contact_value, data["inviteUrl"])

        override = request_factory.post(
            f"/api/v1/hr/staff/{self.staff.id}/account-invitations",
            data=b'{"email":"attacker@example.com"}',
            content_type="application/json",
        )
        override.user = self.admin
        with mock.patch(
            "hr_staff.api.account_invitations.make_staff_context",
            return_value=context,
        ):
            response = account_api.issue_account_invitation(
                override, self.staff.id
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_public_activation_requires_csrf_and_never_auto_logs_in(self):
        _invitation, token = self.issue()
        path = f"/activate-account/{token}/"
        browser = Client(enforce_csrf_checks=True)

        page = browser.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "激活教职工账号")
        self.assertEqual(page["Referrer-Policy"], "no-referrer")
        self.assertEqual(page["Cache-Control"], "no-store")

        missing_csrf = browser.post(
            path,
            {
                "username": "browser-teacher",
                "password": self.password,
                "confirm_password": self.password,
            },
        )
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertFalse(User.objects.filter(username="browser-teacher").exists())

        csrf = browser.cookies["csrftoken"].value
        accepted = browser.post(
            path,
            {
                "username": "browser-teacher",
                "password": self.password,
                "confirm_password": self.password,
            },
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(accepted["Location"], "/account-activation-complete/")
        self.assertNotIn("_auth_user_id", browser.session)

        complete = browser.get(accepted["Location"])
        self.assertEqual(complete.status_code, 200)
        self.assertContains(complete, "账号已激活")
        self.assertContains(complete, "browser-teacher")
        self.assertNotIn("_auth_user_id", browser.session)
