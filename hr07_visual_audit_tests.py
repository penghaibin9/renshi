"""Real Chromium acceptance for the HR07 V2 contract Authority workspace."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr07VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True
    ROUTES = (
        ("ledger", "/hr/contracts/"),
        ("rules", "/hr/contracts/rules/"),
        ("signing", "/hr/contracts/signing/"),
        ("changes", "/hr/contracts/changes/"),
        ("risks", "/hr/contracts/risks/"),
    )

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffMaster

        self.company = Company.objects.create(
            company="跃科 HR07 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 7 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr07-visual.png", b"hr07-visual", content_type="image/png"),
        )
        self.user = get_user_model().objects.create_superuser(
            username="hr07-visual-auditor",
            email="hr07-visual@example.invalid",
            password="hr07-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR07",
            employee_last_name="视觉验收员",
            email="hr07-employee@example.invalid",
            phone="13800000007",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="真实合同测试教师",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="HR07-CLICK-001",
            current_employment_status="ACTIVE",
        )
        self.relationship = HrEmploymentRelationship.objects.create(
            tenant_id=self.company.pk,
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="PUBLIC_INSTITUTION",
            effective_from=date(2024, 9, 1),
            status="ACTIVE",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")) / "HR07-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def browser_context(self, browser, viewport=None):
        context = browser.new_context(
            viewport=viewport or {"width": 1440, "height": 1000},
            device_scale_factor=1,
        )
        context.add_cookies([
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": self.session_cookie,
                "url": self.live_server_url,
            }
        ])
        return context

    @staticmethod
    def record_console(page, page_errors, console_errors):
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    def test_capture_all_hr07_workspaces_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser)
                page = context.new_page()
                self.record_console(page, page_errors, console_errors)

                def record_response(response):
                    if ("/api/v1/hr/" in response.url or "/api/hr/v1/" in response.url) and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                for section, route in self.ROUTES:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(page.locator(f'[data-module="HR07"][data-hr07-section="{section}"]').count(), 1)
                    self.assertEqual(page.locator(".hr07-nav a").count(), 5)
                    self.assertEqual(page.locator(".hr07-hero").count(), 0)
                    self.assertEqual(page.locator(".hr-v2-pagehead").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"desktop-{section}.png"), full_page=True)

                page.set_viewport_size({"width": 390, "height": 844})
                for section, route in self.ROUTES:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"mobile-{section}.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR07 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR07 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR07 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR07 static failures: " + " | ".join(static_failures))

    def test_real_browser_completes_initial_signing_and_renewal_lifecycle(self):
        from playwright.sync_api import sync_playwright

        from hr_contracts.models import HrContractAgreement, HrContractCase, HrContractVersion

        page_errors, console_errors, api_failures = [], [], []
        today = date.today()
        initial_end = today + timedelta(days=365)
        successor_start = initial_end
        successor_end = today + timedelta(days=730)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser)
                page = context.new_page()
                self.record_console(page, page_errors, console_errors)
                page.on(
                    "response",
                    lambda response: api_failures.append(f"{response.status} {response.url}")
                    if ("/api/v1/hr/" in response.url or "/api/hr/v1/" in response.url) and response.status >= 400
                    else None,
                )

                response = page.goto(self.live_server_url + "/hr/contracts/", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.click("#hr07-create-toggle")
                page.fill('input[name="agreementNo"]', "HT-CLICK-07001")
                page.fill('input[name="title"]', "真实浏览器专任教师聘用合同")
                page.select_option('select[name="agreementType"]', "FIXED_TERM")
                page.fill("#hr07-staff-keyword", self.staff.staff_no)
                page.click("#hr07-staff-search")
                page.wait_for_selector(".hr07-picker-option", timeout=8000)
                page.locator(".hr07-picker-option").first.click()
                page.wait_for_function(
                    """() => {
                      const node = document.querySelector('select[name="employmentRelationshipId"]');
                      return node && !node.disabled && Boolean(node.value);
                    }""",
                    timeout=8000,
                )
                with page.expect_response(lambda item: item.url.endswith("/api/v1/hr/contracts/agreements") and item.request.method == "POST") as created_info:
                    page.click('#hr07-create-form button[type="submit"]')
                self.assertEqual(created_info.value.status, 201)
                page.wait_for_function("() => document.body.innerText.includes('HT-CLICK-07001')", timeout=8000)
                page.screenshot(path=str(self.out_dir / "desktop-created-agreement.png"), full_page=True)

                page.click('a[href="/hr/contracts/signing/"]')
                page.wait_for_url("**/hr/contracts/signing/")
                page.wait_for_function("() => document.getElementById('hr07-sign-agreement-id').options.length > 1", timeout=8000)
                page.select_option("#hr07-sign-agreement-id", label="HT-CLICK-07001 · 真实浏览器专任教师聘用合同 · 真实合同测试教师 · HR07-CLICK-001")
                page.click('#hr07-sign-query button[type="submit"]')
                page.wait_for_selector("#hr07-sign-form", timeout=8000)
                page.fill('#hr07-sign-form input[name="effectiveFrom"]', today.isoformat())
                page.fill('#hr07-sign-form input[name="effectiveTo"]', initial_end.isoformat())
                page.fill('#hr07-sign-form input[name="signedAt"]', today.isoformat() + "T09:00")
                page.fill('#hr07-sign-form input[name="signedDocumentRef"]', "ESIGN-CLICK-INITIAL-07001")
                page.fill('#hr07-sign-form textarea[name="contentSnapshot"]', "首版正式条款，经双方签署确认。")
                with page.expect_response(
                    lambda item: item.url.endswith("/versions/sign")
                    and item.request.method == "POST"
                ) as initial_sign_info:
                    page.click('#hr07-sign-form button[type="submit"]')
                self.assertEqual(
                    initial_sign_info.value.status,
                    201,
                    initial_sign_info.value.text(),
                )
                page.wait_for_selector("#hr07-activate-form", timeout=8000)
                with page.expect_response(
                    lambda item: item.url.endswith("/activate")
                    and item.request.method == "POST"
                ) as initial_activate_info:
                    page.click('#hr07-activate-form button[type="submit"]')
                self.assertEqual(
                    initial_activate_info.value.status,
                    200,
                    initial_activate_info.value.text(),
                )
                page.wait_for_function(
                    "() => document.getElementById('hr07-sign-workspace').innerText.includes('正式生效版本')",
                    timeout=8000,
                )

                page.wait_for_function("() => document.querySelector('[data-agreement-select]').options.length > 1", timeout=8000)
                renewal = page.locator('[data-lifecycle-create-form]').first
                renewal.locator('select[name="agreementId"]').select_option(label="HT-CLICK-07001 · 真实浏览器专任教师聘用合同 · 真实合同测试教师 · HR07-CLICK-001")
                renewal.locator('input[name="caseNo"]').fill("RENEW-CLICK-07001")
                renewal.locator('input[name="requestedEffectiveFrom"]').fill(successor_start.isoformat())
                renewal.locator('input[name="requestedEffectiveTo"]').fill(successor_end.isoformat())
                renewal.locator('textarea[name="reasonText"]').fill("聘期届满，经审核继续聘用。")
                renewal.locator('button[type="submit"]').click()

                actions = page.locator('[data-lifecycle-action-form]').first
                page.wait_for_function("() => document.querySelector('[data-lifecycle-action-form] [data-case-select]').value !== ''", timeout=8000)
                for action in ("submit", "approve"):
                    button = actions.locator(f'[data-case-action="{action}"]')
                    button.wait_for(state="visible", timeout=8000)
                    button.click()
                actions.locator('[data-case-action="sign"]').wait_for(state="visible", timeout=8000)
                actions.locator('input[name="signedAt"]').fill(today.isoformat() + "T10:00")
                actions.locator('input[name="signedDocumentRef"]').fill("ESIGN-CLICK-RENEW-07001")
                actions.locator('textarea[name="contentSnapshot"]').fill("续签正式条款，经双方签署确认。")
                actions.locator('[data-case-action="sign"]').click()
                actions.locator('[data-case-action="activate"]').wait_for(state="visible", timeout=8000)
                actions.locator('input[name="asOf"]').fill(successor_start.isoformat())
                actions.locator('[data-case-action="activate"]').click()
                page.wait_for_function("() => document.querySelector('[data-lifecycle-result]').innerText.includes('当前 已生效')", timeout=8000)
                page.screenshot(path=str(self.out_dir / "desktop-renewal-effective.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        agreement = HrContractAgreement.objects.get(tenant_id=self.company.pk, agreement_no="HT-CLICK-07001")
        case = HrContractCase.objects.get(tenant_id=self.company.pk, case_no="RENEW-CLICK-07001")
        versions = list(HrContractVersion.objects.filter(agreement=agreement).order_by("version_no"))
        self.assertEqual(agreement.status, "ACTIVE")
        self.assertEqual(case.status, "EFFECTIVE")
        self.assertEqual([item.status for item in versions], ["SUPERSEDED", "EFFECTIVE"])
        self.assertEqual(page_errors, [], "HR07 lifecycle page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR07 lifecycle console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR07 lifecycle API failures: " + " | ".join(api_failures))
