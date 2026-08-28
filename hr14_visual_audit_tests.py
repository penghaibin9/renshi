"""Real Chromium acceptance for the HR14 appointment V2 workspace."""

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
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr14-visual-media-"))
class Hr14VisualAuditTests(StaticLiveServerTestCase):
    """Verify HR14 V2 keeps all real ranking/publicity/term Authority surfaces."""

    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR14 视觉验收学校",
            hq=True,
            address="长沙市岗位聘任路 14 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr14-visual.png",
                b"hr14-visual",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr14-visual-auditor",
            email="hr14-visual@example.invalid",
            password="hr14-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])

        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR14",
            employee_last_name="视觉验收员",
            email="hr14-employee@example.invalid",
            phone="13800000014",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=self.employee,
        )
        if work_info.company_id_id != self.company.pk:
            work_info.company_id = self.company
            work_info.save(update_fields=["company_id"])

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value

        self.out_dir = Path(
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")
        ) / "HR14-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr14_v2_desktop_and_mobile(self):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        routes = [
            "/hr/appointments/",
            "/hr/appointments/policies/",
            "/hr/appointments/quota/",
            "/hr/appointments/competitions/",
            "/hr/appointments/applications/",
            "/hr/appointments/ranking/",
            "/hr/appointments/publicity/",
            "/hr/appointments/appointments/",
            "/hr/appointments/term-changes/",
        ]
        page_errors: list[str] = []
        console_errors: list[str] = []
        static_failures: list[str] = []
        page_script_responses: list[str] = []
        dashboard_responses: list[str] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
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
                    lambda msg: console_errors.append(msg.text)
                    if msg.type == "error"
                    else None,
                )

                def record_response(response):
                    if "/static/hr/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/js/pages/" in response.url:
                        page_script_responses.append(f"{response.status} {response.url}")
                    if "/api/v1/hr/appointments/dashboard/" in response.url:
                        dashboard_responses.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                response = page.goto(
                    self.live_server_url + routes[0],
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR14']").count(), 1)
                self.assertEqual(page.locator(".hr14-nav a").count(), 9)
                self.assertEqual(page.locator(".hr14-process__step").count(), 6)
                self.assertEqual(page.locator(".hr14-hero").count(), 0)
                self.assertEqual(page.locator("#hr14-kpis .hr14-kpi").count(), 6)

                script_sources = page.evaluate(
                    """() => Array.from(document.scripts)
                      .map((script) => script.src || '<inline>')"""
                )
                booted = page.locator("[data-module='HR14']").get_attribute(
                    "data-hr14-booted"
                )
                try:
                    page.wait_for_function(
                        """() => {
                          const value = document.querySelector('#hr14-kpis .hr14-kpi b');
                          return value && value.textContent.trim() !== '—';
                        }""",
                        timeout=8000,
                    )
                except PlaywrightTimeoutError as exc:
                    diagnostic = (
                        f"script_sources={script_sources}; booted={booted}; "
                        f"script_responses={page_script_responses}; "
                        f"dashboard_responses={dashboard_responses}; "
                        f"page_errors={page_errors}; console_errors={console_errors}; "
                        f"static_failures={static_failures}"
                    )
                    self.fail(f"HR14 V2 boot did not settle: {diagnostic}; {exc}")

                loaded_styles = page.evaluate(
                    """() => Array.from(document.styleSheets)
                      .map((sheet) => sheet.href || '')
                      .filter(Boolean)"""
                )
                diagnostic = (
                    f"styles={loaded_styles}; scripts={script_sources}; "
                    f"script_responses={page_script_responses}; "
                    f"dashboard_responses={dashboard_responses}; "
                    f"page_errors={page_errors}; console_errors={console_errors}; "
                    f"static_failures={static_failures}"
                )
                self.assertTrue(
                    any("/hr/css/hr-v2.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertTrue(
                    any("/hr/css/hr14-appointment.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertTrue(
                    any("/hr/js/pages/hr14-appointment.js" in src for src in script_sources),
                    diagnostic,
                )
                self.assertEqual(booted, "true", diagnostic)
                self.assertEqual(page_errors, [], diagnostic)
                self.assertEqual(static_failures, [], diagnostic)
                page.screenshot(
                    path=str(self.out_dir / "desktop-overview.png"),
                    full_page=True,
                )

                for route in routes[1:]:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, f"No HTTP response for HR14 {route}")
                    self.assertEqual(
                        response.status,
                        200,
                        f"HR14 {route} returned HTTP {response.status}",
                    )
                    self.assertEqual(
                        page.locator("[data-module='HR14']").count(),
                        1,
                        f"HR14 V2 shell missing at {route}",
                    )

                    if route.endswith("/ranking/"):
                        self.assertEqual(
                            page.locator("#hr14live-ranking-history").count(),
                            1,
                            "HR14 ranking Authority history was lost during V2 migration",
                        )
                    elif route.endswith("/publicity/"):
                        self.assertEqual(
                            page.locator("#hr14live-publicity").count(),
                            1,
                            "HR14 publicity/objection Authority UI was lost during V2 migration",
                        )
                    elif route.endswith("/term-changes/"):
                        self.assertEqual(
                            page.locator("#hr14term-root").count(),
                            1,
                            "HR14 term governance UI was lost during V2 migration",
                        )
                        self.assertEqual(
                            page.locator("#hr14effect-root").count(),
                            1,
                            "HR14 apply-effect UI was lost during V2 migration",
                        )

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(
                    self.live_server_url + routes[0],
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR14']").count(), 1)
                self.assertEqual(
                    page.locator(".hr-v2-mobile-section-switcher").count(), 1
                )
                page.screenshot(
                    path=str(self.out_dir / "mobile-overview.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "HR14 browser page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            console_errors,
            [],
            "HR14 browser console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR14 HR static failures: " + " | ".join(static_failures),
        )
