"""Actual activation retry, explicit login and HR17 identity on Django/MySQL.

Synthetic HR03 staff and a service-issued invitation are prerequisites. Account,
SELF membership and account-link final states must be created by browser POST.
No HTTP replacement, forced clicks, authentication-cookie injection or traces
containing invitation secrets. This is not the admin invitation UI acceptance.
"""
from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings


def _read_on_worker(reader, **identifiers):
    """Keep synchronous DB/session reads outside Playwright's active loop.

    Callers pass scalar identifiers, not model instances, QuerySets or database
    handles. The worker evaluates the whole checkpoint and owns/closes its DB
    connections. Only primitive evidence returns to the browser test thread.
    """
    def read():
        from django.db import close_old_connections, connections

        try:
            close_old_connections()
            return reader(**identifiers)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="activation-readback") as worker:
        return worker.submit(read).result()


def _read_validation_checkpoint(*, tenant_id, staff_id, invitation_id, username):
    from hr_staff.models import HrAccountInvitation, HrAccountLink, HrStaffAuditEvent

    invitation = HrAccountInvitation.objects.values(
        "accepted_at", "accepted_user_id"
    ).get(tenant_id=tenant_id, pk=invitation_id)
    return {
        "userExists": get_user_model().objects.filter(username=username).exists(),
        "invitationAccepted": invitation["accepted_at"] is not None,
        "invitationUserAssigned": invitation["accepted_user_id"] is not None,
        "accountLinkExists": HrAccountLink.objects.filter(
            tenant_id=tenant_id, staff_id=staff_id
        ).exists(),
        "acceptedAuditCount": HrStaffAuditEvent.objects.filter(
            tenant_id=tenant_id, business_id=invitation_id,
            action="StaffAccountInvitationAccepted",
        ).count(),
    }


def _read_session_checkpoint(*, session_engine, session_key, bearer):
    # The configured session backend may query MySQL. It must be constructed,
    # read and discarded on this worker, too. Never return or log the session.
    store = import_module(session_engine).SessionStore(session_key=session_key)
    data = store.load()
    return {
        "authenticated": "_auth_user_id" in data,
        "bearerPersisted": bearer in str(data),
        "completionPending": "account_activation_complete" in data,
    }


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "explicit real browser gate")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="hr-activation-browser-"))
class AccountActivationBrowserTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from hr_staff.models import HrPerson, HrPersonContact, HrStaffMaster
        from hr_staff.services.account_invitation_service import AccountInvitationService

        self.company = Company.objects.create(
            company="合成账号激活验收学校", address="测试环境",
            country="CN", state="Hunan", city="Changsha", zip="410000",
        )
        self.person = HrPerson.objects.create(
            tenant_id=self.company.pk, legal_name="合成账号验收教师", status="ACTIVE"
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk, person_id=self.person,
            staff_no="ACTIVATION-BROWSER-001", current_employment_status="ACTIVE",
        )
        HrPersonContact.objects.create(
            tenant_id=self.company.pk, person_id=self.person,
            contact_kind="WORK_EMAIL", contact_value="activation@example.invalid",
            masked_display="a***@example.invalid", is_primary=True, is_verified=True,
        )
        self.invitation, self.token = AccountInvitationService(self.company.pk).issue(
            staff_id=self.staff.pk
        )
        self.path = f"/activate-account/{self.invitation.id}/"
        self.password = "Browser-Activation-Only-7519"
        self.out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "ACCOUNT-ACTIVATION-REAL"
        self.out.mkdir(parents=True, exist_ok=True)

    def assert_private(self, response):
        directives = {item.strip().lower() for item in response.headers.get("cache-control", "").split(",")}
        self.assertTrue({"no-store", "private", "max-age=0"}.issubset(directives))
        self.assertNotIn("public", directives)
        self.assertEqual(response.headers.get("referrer-policy"), "no-referrer")

    def exercise(self, mode, width):
        from playwright.sync_api import expect, sync_playwright
        from base.models import CompanyGroupAssignment
        from hr_self.services.identity_service import SelfIdentityService
        from hr_staff.models import HrAccountLink, HrStaffAuditEvent

        name = f"activation-{mode}-teacher"
        page_errors, unsafe_urls, post_statuses = [], [], []
        completed_gets = []
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": width, "height": 844 if width <= 760 else 1000})
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("request", lambda req: unsafe_urls.append(True) if self.token in req.url else None)
                page.on("response", lambda res: completed_gets.append(res.status) if urlsplit(res.url).path == "/account-activation-complete/" and res.request.method == "GET" else None)
                try:
                    initial = page.goto(self.live_server_url + self.path + "#" + self.token, wait_until="networkidle")
                except Exception:
                    self.fail("Activation navigation failed; bearer URL omitted")
                self.assertEqual(initial.status, 200)
                self.assert_private(initial)
                expect(page).to_have_url(self.live_server_url + self.path)
                self.assertNotIn(self.token, page.content())
                page.screenshot(path=str(self.out / f"{mode}-initial.png"), full_page=True)
                page.get_by_label("登录账号", exact=True).fill(name)
                page.get_by_label("设置密码", exact=True).fill("short")
                page.get_by_label("再次输入密码", exact=True).fill("short")
                with page.expect_response(lambda r: urlsplit(r.url).path == self.path and r.request.method == "POST") as invalid:
                    page.get_by_role("button", name="完成账号激活", exact=True).click()
                post_statuses.append(invalid.value.status)
                self.assertEqual(invalid.value.status, 400)
                self.assert_private(invalid.value)
                self.assertFalse(invalid.value.json()["ok"])
                self.assertIn("password", invalid.value.json()["errors"])
                expect(page.locator("#id_password")).to_be_focused()
                expect(page.locator("#error-password")).to_be_visible()
                expect(page.locator("#account-invitation-submit")).to_be_enabled()
                self.assertNotIn(self.token, page.content())
                self.assertEqual(page.evaluate("[localStorage.length,sessionStorage.length]"), [0, 0])
                page.screenshot(path=str(self.out / f"{mode}-validation-error.png"), full_page=True)
                # Check the rejected write BEFORE submitting corrected input;
                # delaying this checkpoint until the end would hide side effects.
                validation_checkpoint = _read_on_worker(
                    _read_validation_checkpoint,
                    tenant_id=self.company.pk, staff_id=str(self.staff.pk),
                    invitation_id=str(self.invitation.pk), username=name,
                )
                self.assertEqual(validation_checkpoint, {
                    "userExists": False, "invitationAccepted": False,
                    "invitationUserAssigned": False, "accountLinkExists": False,
                    "acceptedAuditCount": 0,
                })

                # Same page and original in-memory invitation, no reissue/reload.
                page.get_by_label("设置密码", exact=True).fill(self.password)
                page.get_by_label("再次输入密码", exact=True).fill(self.password)
                with page.expect_response(lambda r: urlsplit(r.url).path == self.path and r.request.method == "POST") as accepted:
                    page.get_by_role("button", name="完成账号激活", exact=True).click()
                post_statuses.append(accepted.value.status)
                self.assertEqual(accepted.value.status, 200)
                self.assertEqual(accepted.value.json(), {"ok": True, "next": "/account-activation-complete/"})
                self.assert_private(accepted.value)
                expect(page).to_have_url(self.live_server_url + "/account-activation-complete/")
                expect(page.get_by_role("heading", name="账号已激活", exact=True)).to_be_visible()
                self.assertEqual(completed_gets, [200])
                cookies = {row["name"]: row["value"] for row in context.cookies()}
                anonymous_checkpoint = _read_on_worker(
                    _read_session_checkpoint, session_engine=settings.SESSION_ENGINE,
                    session_key=cookies.get(settings.SESSION_COOKIE_NAME),
                    bearer=self.token,
                )
                self.assertEqual(anonymous_checkpoint, {
                    "authenticated": False, "bearerPersisted": False,
                    "completionPending": False,
                })
                page.screenshot(path=str(self.out / f"{mode}-complete.png"), full_page=True)

                page.goto(self.live_server_url + "/login/?next=/hr/self/", wait_until="networkidle")
                page.locator("#username").fill(name)
                page.locator("#password").fill(self.password)
                with page.expect_response(lambda r: urlsplit(r.url).path == "/hr/self/" and r.request.is_navigation_request()) as self_page:
                    page.locator("button.yk-login-submit").click()
                self.assertEqual(self_page.value.status, 200)
                expect(page.locator("[data-module='HR17']")).to_be_visible()
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth-innerWidth"), 1)
                page.screenshot(path=str(self.out / f"{mode}-self-login.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        user = get_user_model().objects.get(username=name)
        link = HrAccountLink.objects.get(staff_id=self.staff, tenant_id=self.company.pk)
        self.assertEqual(link.auth_user_id, user.pk)
        self.assertEqual(link.link_status, "ACTIVE")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password(self.password))
        membership = CompanyGroupAssignment.objects.get(user=user, company=self.company)
        self.assertEqual(set(membership.group.permissions.values_list("codename", flat=True)), {"hr.self.view"})
        self.assertEqual(SelfIdentityService(self.company.pk).resolve(user).staff_id, self.staff.pk)
        self.assertEqual(HrStaffAuditEvent.objects.filter(
            tenant_id=self.company.pk, business_id=str(self.invitation.id), action="StaffAccountInvitationAccepted"
        ).count(), 1)
        self.assertEqual(page_errors, [])
        self.assertEqual(unsafe_urls, [])
        self.assertEqual(post_statuses, [400, 200])
        (self.out / f"{mode}-seal.json").write_text(json.dumps({
            "productSha": os.getenv("HR_PRODUCT_SHA", "UNSPECIFIED"),
            "checkoutSha": os.getenv("GITHUB_SHA", "LOCAL"),
            "case": "synthetic staff -> invitation -> validation retry -> explicit login -> HR17",
            "mode": mode, "result": "PASS", "activationPostStatuses": post_statuses,
            "acceptedAuditCount": 1, "autoLogin": False, "httpReplacements": False,
            "unsafeUrlCount": 0, "pageErrors": [],
            "validationCheckpoint": validation_checkpoint,
            "anonymousSessionCheckpoint": anonymous_checkpoint,
            "readbackExecution": "dedicated-thread-owned-connections",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_desktop_validation_retry_and_self_login(self):
        self.exercise("desktop", 1440)

    def test_mobile_validation_retry_and_self_login(self):
        self.exercise("mobile", 390)
