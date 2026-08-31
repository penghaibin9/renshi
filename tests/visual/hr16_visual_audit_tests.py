"""Real Chromium acceptance for the HR16 exit V2 workspace."""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr16-visual-media-"))
class Hr16VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True
    routes = [
        ("overview", "/hr/exit/"), ("cases", "/hr/exit/cases/"),
        ("handover", "/hr/exit/handover/"), ("settlement", "/hr/exit/settlement/"),
        ("retirement-precheck", "/hr/exit/retirement-precheck/"),
        ("retirement-facts", "/hr/exit/retirement-facts/"),
        ("effects", "/hr/exit/effects/"), ("archive", "/hr/exit/archive/"),
    ]

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_exit.models import ExitCase

        self.company = Company.objects.create(
            company="跃科 HR16 视觉验收学校", hq=True, address="长沙市离退路 16 号",
            country="CN", state="Hunan", city="Changsha", zip="410000",
            icon=SimpleUploadedFile("hr16.png", b"hr16", content_type="image/png"),
        )
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="hr16-visual-auditor", email="hr16-visual@example.invalid",
            password="hr16-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        employee = Employee.objects.create(
            employee_user_id=self.user, employee_first_name="HR16", employee_last_name="视觉验收员",
            email="hr16-employee@example.invalid", phone="13800000016", is_active=True,
        )
        work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        if work.company_id_id != self.company.pk:
            work.company_id = self.company
            work.save(update_fields=["company_id"])
        self.case = ExitCase.objects.create(
            tenant_id=self.company.pk, case_no="LX-2026-0016", person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(), exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.DRAFT, requested_date=date(2026, 8, 30),
            last_working_date=date(2026, 9, 15), planned_employment_end_date=date(2026, 9, 15),
        )
        client = Client(); client.force_login(self.user)
        session = client.session; session["selected_company"] = str(self.company.pk); session["otp_code_verified"] = True; session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR16-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_all_routes_and_real_case_submit(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright must be installed for HR visual audit") from exc
        page_errors, console_errors, static_failures, api_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.session_cookie, "url": self.live_server_url}])
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

                def track(response):
                    if "/static/hr/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")
                    if "/api/v1/hr/exit/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", track)
                for slug, route in self.routes:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response); self.assertEqual(response.status, 200)
                    self.assertEqual(page.locator("[data-module='HR16']").count(), 1)
                    self.assertEqual(page.locator(".hr16-nav a").count(), 8)
                    self.assertEqual(page.locator("#hr16-kpis .hr16-kpi").count(), 6)
                    if slug == "overview": self.assertEqual(page.locator(".hr16-process__step").count(), 6)
                    else: self.assertEqual(page.locator(".hr16-action-card").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"desktop-{slug}.png"), full_page=True)

                response = page.goto(self.live_server_url + "/hr/exit/cases/", wait_until="networkidle")
                self.assertEqual(response.status, 200)
                submit = page.locator('[data-transition="submit"]').first
                self.assertEqual(submit.count(), 1)
                with page.expect_response(lambda item: "/submit/" in item.url and item.request.method == "POST") as response_info:
                    submit.click()
                self.assertEqual(response_info.value.status, 200)
                page.locator(".hr16-action-result.ok").wait_for(state="visible")
                self.assertIn("待审批", page.locator(".hr16-action-result").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-cases-submitted.png"), full_page=True)

                page.set_viewport_size({"width": 390, "height": 844})
                for slug, route in self.routes:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response); self.assertEqual(response.status, 200)
                    self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"mobile-{slug}.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_exit.models import ExitCase
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, ExitCase.Status.SUBMITTED)
        self.assertEqual(page_errors, [], "HR16 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR16 console errors: " + " | ".join(console_errors))
        self.assertEqual(static_failures, [], "HR16 static failures: " + " | ".join(static_failures))
        self.assertEqual(api_failures, [], "HR16 API failures: " + " | ".join(api_failures))
