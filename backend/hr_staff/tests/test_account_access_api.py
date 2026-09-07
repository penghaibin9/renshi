"""Account-access readback and data-scope contracts for HR03 administrator UI."""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from base.models import Company
from hr_staff.api import account_invitations as account_api
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import (
    HrAccountInvitation,
    HrAccountLink,
    HrPerson,
    HrPersonContact,
    HrStaffMaster,
)


User = get_user_model()


class AccountAccessApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.company = Company.objects.create(
            company="Account Access Scope School",
            address="",
            country="CN",
            state="",
            city="",
            zip="",
        )
        self.admin = User.objects.create_superuser(
            username="account-access-root",
            email="",
            password="Admin-Account-Access-7429",
        )
        self.person = HrPerson.objects.create(
            tenant_id=self.company.id,
            legal_name="账号管理测试教师",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.id,
            person_id=self.person,
            staff_no="ACCOUNT-001",
            current_employment_status="ACTIVE",
        )
        self.contact = HrPersonContact.objects.create(
            tenant_id=self.company.id,
            person_id=self.person,
            contact_kind=HrPersonContact.ContactKind.WORK_EMAIL,
            contact_value="account.owner@example.edu.cn",
            masked_display="a***@example.edu.cn",
            is_primary=True,
            is_verified=True,
        )

    def context(self, *, scope_type="SCHOOL", staff_ids=()):
        return HrStaffRequestContext(
            tenant_id=self.company.id,
            scope=HrStaffScope(
                scope_type=scope_type,
                staff_ids=frozenset(staff_ids),
            ),
        )

    def request(self, method, path):
        if method == "POST":
            request = self.factory.post(
                path,
                data=b"{}",
                content_type="application/json",
            )
        else:
            request = self.factory.get(path)
        request.user = self.admin
        return request

    def test_get_account_access_returns_masked_current_state_without_token_digest(self):
        invitation = HrAccountInvitation.objects.create(
            tenant_id=self.company.id,
            staff_id=self.staff,
            invited_email=self.contact.contact_value,
            token_digest="sha256$" + "a" * 64,
            expires_at=timezone.now() + timedelta(hours=2),
            created_by_user_id=self.admin.id,
        )
        request = self.request(
            "GET",
            f"/api/v1/hr/staff/{self.staff.id}/account-invitations",
        )

        from unittest import mock

        with mock.patch(
            "hr_staff.api.account_invitations.make_staff_context",
            return_value=self.context(),
        ):
            response = account_api.issue_account_invitation(
                request,
                self.staff.id,
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        data = payload["data"]
        self.assertEqual(payload["schemaVersion"], "hr03.account-access.1")
        self.assertTrue(data["emailReady"])
        self.assertNotEqual(data["emailMasked"], self.contact.contact_value)
        self.assertEqual(
            data["latestInvitation"]["invitationId"],
            str(invitation.id),
        )
        self.assertEqual(data["latestInvitation"]["status"], "PENDING")
        rendered = response.content.decode("utf-8")
        self.assertNotIn(invitation.token_digest, rendered)
        self.assertNotIn(self.contact.contact_value, rendered)

    def test_get_account_access_returns_link_history_and_blocks_false_unlinked_state(
        self,
    ):
        user = User.objects.create_user(
            username="linked-account-owner",
            password="Linked-Account-7429",
        )
        link = HrAccountLink.objects.create(
            tenant_id=self.company.id,
            staff_id=self.staff,
            auth_user_id=user.id,
            auth_identifier=user.username,
            link_status=HrAccountLink.LinkStatus.UNLINKED,
            linked_at=timezone.now(),
            unlinked_at=timezone.now(),
        )
        request = self.request(
            "GET",
            f"/api/v1/hr/staff/{self.staff.id}/account-invitations",
        )

        from unittest import mock

        with mock.patch(
            "hr_staff.api.account_invitations.make_staff_context",
            return_value=self.context(),
        ):
            response = account_api.issue_account_invitation(
                request,
                self.staff.id,
            )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)["data"]
        self.assertTrue(data["hasLinkHistory"])
        self.assertEqual(data["links"][0]["linkId"], str(link.id))
        self.assertEqual(data["links"][0]["identifier"], user.username)
        self.assertEqual(data["links"][0]["status"], "UNLINKED")
        self.assertNotIn("auth_user_id", response.content.decode("utf-8"))

    def test_revoke_requires_staff_to_remain_inside_current_data_scope(self):
        invitation = HrAccountInvitation.objects.create(
            tenant_id=self.company.id,
            staff_id=self.staff,
            invited_email=self.contact.contact_value,
            token_digest="sha256$" + "b" * 64,
            expires_at=timezone.now() + timedelta(hours=2),
            created_by_user_id=self.admin.id,
        )
        other_person = HrPerson.objects.create(
            tenant_id=self.company.id,
            legal_name="范围内另一教师",
            status="ACTIVE",
        )
        other_staff = HrStaffMaster.objects.create(
            tenant_id=self.company.id,
            person_id=other_person,
            staff_no="ACCOUNT-OTHER-002",
            current_employment_status="ACTIVE",
        )
        request = self.request(
            "POST",
            f"/api/v1/hr/account-invitations/{invitation.id}/revoke",
        )

        from unittest import mock

        with mock.patch(
            "hr_staff.api.account_invitations.make_staff_context",
            return_value=self.context(
                scope_type="SELF",
                staff_ids=(other_staff.id,),
            ),
        ):
            response = account_api.revoke_account_invitation(
                request,
                invitation.id,
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "STAFF_SCOPE_DENIED",
        )
        invitation.refresh_from_db()
        self.assertIsNone(invitation.revoked_at)
