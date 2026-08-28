"""Real Chromium acceptance for the HR17 SELF V2 workspace."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr17-visual-media-"))
class Hr17VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR17 视觉验收学校",
            hq=True,
            address="长沙市教职工服务路 17 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr17.png", b"hr17", content_type="image/png"),
        )
        self.user = User.objects.create_superuser(
            username="hr17-visual-auditor",
            email="hr17-visual@example.invalid",
            password="hr17-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR17",
            employee_last_name="本人验收员",
            email="hr17-employee@example.invalid",
            phone="13800000017",
            is_active=True,
        )
        work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        if work.company_id_id != self.company.pk:
            work.company_id = self.company
            work.save(update_fields=["company_id"])

        self.person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="HR17 本人验收员",
            preferred_name="本人验收员",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            staff_no="HR17-SELF-001",
            legacy_employee_id=self.employee.pk,
            current_employment_status="ACTIVE",
        )
        other_person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="HR17 他人负例",
            preferred_name="他人负例",
        )
        self.other_staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=other_person,
            staff_no="HR17-OTHER-999",
            legacy_employee_id=99999917,
            current_employment_status="ACTIVE",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")) / "HR17-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr17_self_v2_desktop_idor_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        routes = [
            "/hr/self/",
            "/hr/self/services/",
            "/hr/self/todos/",
            "/hr/self/progress/",
            "/hr/self/files/",
            "/hr/self/payslips/",
            "/hr/self/contracts/",
        ]
        page_errors = []
        console_errors = []
        static_failures = []
        bootstrap_requests = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    device_scale_factor=1,
                )
                context.add_cookies(
                    [
                        {
                            "name": settings.SESSION_COOKIE_NAME,
                            "value": self.session_cookie,
                            "url": self.live_server_url,
                        }
                    ]
                )
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                page.on(
                    "response",
                    lambda response: static_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/" in response.url and response.status >= 400
                    else None,
                )
                page.on(
                    "request",
                    lambda request: bootstrap_requests.append(request.url)
                    if "/api/v1/hr/self/bootstrap/" in request.url
                    else None,
                )

                response = page.goto(self.live_server_url + routes[0], wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR17']").count(), 1)
                self.assertEqual(page.locator(".hr17-nav a").count(), 7)
                self.assertEqual(page.locator(".hr17-hero").count(), 0)
                self.assertEqual(page.locator("#hr17-kpis .hr17-kpi").count(), 4)
                page.wait_for_function(
                    """() => {
                      const value = document.querySelector('#hr17-kpis .hr17-kpi b');
                      return value && value.textContent.trim() !== '—';
                    }""",
                    timeout=8000,
                )
                page.wait_for_function(
                    """() => document.querySelector('#hr17-identity')?.textContent.includes('HR17-SELF-001')""",
                    timeout=8000,
                )
                self.assertIn("HR17-SELF-001", page.locator("#hr17-identity").inner_text())
                self.assertNotIn("HR17-OTHER-999", page.locator("body").inner_text())

                styles = page.evaluate(
                    """() => Array.from(document.styleSheets).map((sheet) => sheet.href || '').filter(Boolean)"""
                )
                diag = (
                    f"styles={styles}; page_errors={page_errors}; "
                    f"console_errors={console_errors}; static_failures={static_failures}"
                )
                self.assertTrue(any("/hr/css/hr-v2.css" in item for item in styles), diag)
                self.assertTrue(any("/hr/css/hr17-self.css" in item for item in styles), diag)
                self.assertEqual(page_errors, [], diag)
                self.assertEqual(static_failures, [], diag)
                page.screenshot(path=str(self.out_dir / "desktop-overview.png"), full_page=True)

                tampered = f"/hr/self/?staff_id={self.other_staff.pk}"
                response = page.goto(self.live_server_url + tampered, wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => document.querySelector('#hr17-identity')?.textContent.includes('HR17-SELF-001')""",
                    timeout=8000,
                )
                body_text = page.locator("body").inner_text()
                self.assertIn("HR17-SELF-001", body_text)
                self.assertNotIn("HR17-OTHER-999", body_text)
                self.assertGreaterEqual(len(bootstrap_requests), 2)
                for url in bootstrap_requests:
                    self.assertNotIn("staff_id=", url)
                    self.assertNotIn("staffId=", url)
                    self.assertNotIn(str(self.other_staff.pk), url)
                page.screenshot(path=str(self.out_dir / "desktop-idor-negative.png"), full_page=True)

                for route in routes[1:]:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200, f"HR17 {route} returned HTTP {response.status}")
                    self.assertEqual(page.locator("[data-module='HR17']").count(), 1)
                    self.assertEqual(page.locator(".hr17-nav a").count(), 7)

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(self.live_server_url + routes[0], wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                self.assertEqual(page.locator("[data-module='HR17']").count(), 1)
                page.screenshot(path=str(self.out_dir / "mobile-overview.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR17 browser page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR17 browser console errors: " + " | ".join(console_errors))
        self.assertEqual(static_failures, [], "HR17 HR static failures: " + " | ".join(static_failures))
