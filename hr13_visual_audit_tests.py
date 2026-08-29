"""Real Chromium acceptance for the HR13 professional-title V2 workspace."""

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
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr13-visual-media-"))
class Hr13VisualAuditTests(StaticLiveServerTestCase):
    """Verify HR13 keeps real routes and Authority UI inside the shared V2 shell."""

    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR13 视觉验收学校",
            hq=True,
            address="长沙市职称评审路 13 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr13-visual.png",
                b"hr13-visual",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr13-visual-auditor",
            email="hr13-visual@example.invalid",
            password="hr13-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])

        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR13",
            employee_last_name="视觉验收员",
            email="hr13-employee@example.invalid",
            phone="13800000013",
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
        ) / "HR13-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr13_v2_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        routes = [
            ("overview", "/hr/titles/"),
            ("applications", "/hr/titles/applications/"),
            ("eligibility", "/hr/titles/eligibility/"),
            ("materials", "/hr/titles/materials/"),
            ("experts", "/hr/titles/experts/"),
            ("deliberation", "/hr/titles/deliberation/"),
            ("publicity", "/hr/titles/publicity/"),
            ("appeals", "/hr/titles/appeals/"),
            ("results", "/hr/titles/results/"),
        ]
        page_errors: list[str] = []
        console_errors: list[str] = []
        static_failures: list[str] = []
        api_failures: list[str] = []

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
                    if "/api/v1/hr/titles/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                response = page.goto(
                    self.live_server_url + routes[0][1],
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR13']").count(), 1)
                self.assertEqual(page.locator(".hr13-nav a").count(), 9)
                self.assertEqual(page.locator(".hr13-process__step").count(), 6)
                self.assertEqual(page.locator(".hr13c-hero").count(), 0)
                self.assertGreaterEqual(page.locator("#hr13c-kpis .hr13c-kpi").count(), 6)
                page.wait_for_function(
                    """() => {
                      const value = document.querySelector('#hr13c-kpis .hr13c-kpi b');
                      return value && value.textContent.trim() !== '—';
                    }""",
                    timeout=8000,
                )

                loaded_styles = page.evaluate(
                    """() => Array.from(document.styleSheets)
                      .map((sheet) => sheet.href || '')
                      .filter(Boolean)"""
                )
                diagnostic = (
                    f"styles={loaded_styles}; page_errors={page_errors}; "
                    f"console_errors={console_errors}; static_failures={static_failures}"
                )
                self.assertTrue(
                    any("/hr/css/hr-v2.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertTrue(
                    any("/hr/css/hr13-title.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertEqual(page_errors, [], diagnostic)
                self.assertEqual(static_failures, [], diagnostic)
                page.screenshot(
                    path=str(self.out_dir / "desktop-overview.png"),
                    full_page=True,
                )

                for route_name, route in routes[1:]:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, f"No HTTP response for HR13 {route}")
                    self.assertEqual(
                        response.status,
                        200,
                        f"HR13 {route} returned HTTP {response.status}",
                    )
                    self.assertEqual(
                        page.locator("[data-module='HR13']").count(),
                        1,
                        f"HR13 V2 shell missing at {route}",
                    )
                    page.screenshot(
                        path=str(self.out_dir / f"desktop-{route_name}.png"),
                        full_page=True,
                    )

                page.set_viewport_size({"width": 390, "height": 844})
                for route_name, route in routes:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(page.locator("[data-module='HR13']").count(), 1)
                    self.assertEqual(
                        page.locator(".hr-v2-mobile-section-switcher").count(), 1
                    )
                    page.screenshot(
                        path=str(self.out_dir / f"mobile-{route_name}.png"),
                        full_page=True,
                    )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "HR13 browser page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            console_errors,
            [],
            "HR13 browser console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR13 static CSS failures: " + " | ".join(static_failures),
        )
        self.assertEqual(
            api_failures,
            [],
            "HR13 API failures: " + " | ".join(api_failures),
        )
