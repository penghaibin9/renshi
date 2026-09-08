"""Real ordinary-teacher login and school-scoped display/navigation acceptance.

Accounts are produced by the existing invitation service as prerequisites.
No HTTP replacements, role-grant changes in the browser, or login-cookie injection.
This suite does not claim invitation-admin UI or all-module role completeness.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.contrib.auth.models import Group, Permission
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "explicit real browser gate")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="teacher-shell-"))
class TeacherShellBrowserTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from hr_staff.models import HrPerson, HrPersonContact, HrStaffMaster
        from hr_staff.services.account_invitation_service import AccountInvitationService

        self.secret = "Synthetic-Shell-Only-9381"
        self.accounts = []
        for key, date_format, time_format in (("a", "YYYY-MM-DD", "HH:mm"), ("b", "DD/MM/YYYY", "hh:mm A")):
            school = Company.objects.create(company=f"合成普通教师显示学校-{key}", address="test", country="CN", state="Hunan", city="Changsha", zip="410000", date_format=date_format, time_format=time_format)
            person = HrPerson.objects.create(tenant_id=school.pk, legal_name=f"合成显示验收教师-{key}", status="ACTIVE")
            staff = HrStaffMaster.objects.create(tenant_id=school.pk, person_id=person, staff_no=f"DISPLAY-{key}", current_employment_status="ACTIVE")
            HrPersonContact.objects.create(tenant_id=school.pk, person_id=person, contact_kind="WORK_EMAIL", contact_value=f"display-{key}@example.invalid", masked_display=f"d***@example.invalid", is_primary=True, is_verified=True)
            invitation, token = AccountInvitationService(school.pk).issue(staff_id=staff.pk)
            user, _link = AccountInvitationService.accept(token, username=f"display-teacher-{key}", password=self.secret)
            self.accounts.append((school, staff, user))
        self.out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "TEACHER-SHELL-REAL"
        self.out.mkdir(parents=True, exist_ok=True)

    def login(self, page, user):
        from playwright.sync_api import expect
        response = page.goto(self.live_server_url + reverse("login"), wait_until="networkidle")
        self.assertEqual(response.status, 200)
        page.locator("#username").fill(user.username)
        page.locator("#password").fill(self.secret)
        bootstrap_path = reverse("hr_self_api:bootstrap")
        with page.expect_response(lambda r: urlsplit(r.url).path == bootstrap_path and r.request.method == "GET") as bootstrap:
            page.locator("button.yk-login-submit").click()
        self.assertEqual(bootstrap.value.status, 200)
        expect(page.locator("[data-module='HR17']")).to_be_visible()
        expect(page.locator("#hr17-identity")).not_to_contain_text("正在读取", timeout=12000)
        self.assertNotIn("Login successful.", page.locator("body").inner_text())

    def test_two_schools_same_browser_do_not_reuse_formats_or_show_admin_menus(self):
        from playwright.sync_api import expect, sync_playwright
        records, requests, errors = [], [], []
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.on("request", lambda req: requests.append(urlsplit(req.url).path))
                for mode, width in (("desktop", 1440), ("mobile", 390)):
                    page.set_viewport_size({"width": width, "height": 1000 if width > 760 else 844})
                    for index, (school, staff, user) in enumerate(self.accounts):
                        self.login(page, user)
                        # Historical unscoped keys are an explicit negative precondition,
                        # not auth state. Production scripts must never consume them.
                        page.evaluate("localStorage.setItem('selectedDateFormat','MM/DD/YYYY');localStorage.setItem('selectedTimeFormat','HH:mm:ss')")
                        response = page.reload(wait_until="networkidle")
                        self.assertEqual(response.status, 200)
                        expect(page.locator("#hr17-identity")).to_contain_text(staff.staff_no, timeout=12000)
                        formats = json.loads(page.locator("#account-display-formats").text_content())
                        self.assertEqual(formats, {"companyId": school.pk, "source": "SCHOOL", "dateFormat": school.date_format, "timeFormat": school.time_format})
                        expected = ["2026-09-08", "17:34"] if index == 0 else ["08/09/2026", "05:34 PM"]
                        self.assertEqual(page.evaluate("[dateFormatter.getFormattedDate('2026-09-08'),timeFormatter.getFormattedTime('05:34 PM')]"), expected)
                        expect(page.locator("#sidebar .hr-module-nav__item, #sidebar .hr-module-nav__home")).to_have_count(1)
                        expect(page.locator("#sidebar .hr-module-nav__item")).to_have_attribute("href", "/hr/self/")
                        expect(page.locator('#sidebar a[href="/hr/staff/"]')).to_have_count(0)
                        self.assertEqual(page.locator('#sidebar .oh-sidebar__company-link[href="/hr/overview"]').count(), 0)
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth-innerWidth"), 1)
                        page.screenshot(path=str(self.out / f"{mode}-school-{index+1}.png"), full_page=True)
                        records.append({"mode": mode, "school": index+1, "dateFormat": formats["dateFormat"], "timeFormat": formats["timeFormat"], "selfIdentityVisible": True})
                self.assertNotIn("/settings/get-date-format/", requests)
                self.assertNotIn("/settings/get-time-format/", requests)
                # Direct management access still fails. These explicit negative
                # probes are distinct from the page's natural network traffic.
                for path in ("/settings/get-date-format/", "/settings/get-time-format/"):
                    self.assertEqual(context.request.get(self.live_server_url + path).status, 403)
                context.close()
            finally:
                browser.close()
        self.assertEqual(errors, [])
        (self.out / "teacher-seal.json").write_text(json.dumps({"productSha": os.getenv("HR_PRODUCT_SHA", "UNSPECIFIED"), "checkoutSha": os.getenv("GITHUB_SHA", "LOCAL"), "result": "PASS", "records": records, "naturalManagementFormatRequests": 0, "explicitManagementReads": [403,403], "pageErrors": errors, "httpReplacements": False}, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_additional_school_role_keeps_management_navigation_and_format_reads(self):
        from base.models import CompanyGroupAssignment
        from playwright.sync_api import expect, sync_playwright
        school, staff, user = self.accounts[0]
        # Separate school role; never pollute the reserved SELF group.
        group = Group.objects.create(name="synthetic-display-manager")
        group.permissions.add(Permission.objects.get(content_type__app_label="base", codename="view_company"))
        CompanyGroupAssignment.objects.create(user=user, company=school, group=group)
        CompanyGroupAssignment.sync_user_group_membership(user, group)
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width":1440,"height":1000})
                page = context.new_page()
                # Multi-role landing intentionally retains the school center;
                # explicitly request the authorised SELF page via login next.
                page.goto(self.live_server_url + reverse("login") + "?next=/hr/self/", wait_until="networkidle")
                page.locator("#username").fill(user.username)
                page.locator("#password").fill(self.secret)
                with page.expect_response(lambda r: urlsplit(r.url).path == "/hr/self/" and r.request.is_navigation_request()) as landed:
                    page.locator("button.yk-login-submit").click()
                self.assertEqual(landed.value.status, 200)
                expect(page.locator("#hr17-identity")).to_contain_text(staff.staff_no, timeout=12000)
                expect(page.locator("#sidebar .hr-module-nav__item, #sidebar .hr-module-nav__home")).to_have_count(18)
                for path, value in (("/settings/get-date-format/", school.date_format), ("/settings/get-time-format/", school.time_format)):
                    response = context.request.get(self.live_server_url + path)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.json()["selected_format"], value)
                page.screenshot(path=str(self.out / "multi-role-navigation.png"), full_page=True)
                context.close()
            finally:
                browser.close()
