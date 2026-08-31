"""Real Chromium visual acceptance for the HR UI V2 foundation.

This test intentionally seeds only the technical school/user identity needed to
render production templates. It does not manufacture HR dashboard KPI, todo or
risk rows just to make screenshots look full; unavailable/empty states must be
visually honest.
"""

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
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-v2-visual-media-"))
class HrV2VisualAuditTests(StaticLiveServerTestCase):
    """Capture migrated HR V2 workspaces at desktop and mobile widths."""

    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR V2 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 2 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr-v2-visual.png",
                b"hr-v2-visual",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr-v2-visual-auditor",
            email="hr-v2-visual@example.invalid",
            password="hr-v2-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])

        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="V2",
            employee_last_name="视觉验收员",
            email="hr-v2-employee@example.invalid",
            phone="13800000004",
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
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")
        ) / "HR01-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr01_v2_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        console_errors: list[str] = []
        api_failures: list[str] = []
        static_failures: list[str] = []

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
                    if (
                        "/api/hr/v1/" in response.url
                        or "/api/v1/hr/" in response.url
                    ) and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/js/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                response = page.goto(
                    self.live_server_url + "/hr/overview",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR01']").count(), 1)
                self.assertEqual(page.locator(".hr-home__module").count(), 18)
                self.assertEqual(page.locator(".hr-v2-conclusion").count(), 3)

                # Always retain the failing first paint before assertions so a red
                # visual gate still leaves concrete browser evidence.
                page.wait_for_timeout(300)
                runtime_state = page.evaluate(
                    """() => ({
                      readyState: document.readyState,
                      hasHrApi: Boolean(window.HrApi),
                      hasHrApiRequest: Boolean(window.HrApi && typeof window.HrApi.request === 'function'),
                      apiClientScript: Array.from(document.scripts).some((s) => s.src.includes('/hr/js/core/api-client.js')),
                      overviewScript: Array.from(document.scripts).some((s) => s.src.includes('/hr/js/pages/overview.js')),
                      skeletonCount: document.querySelectorAll('.hr-v2-conclusion .hr-skeleton').length,
                      priorityTodoHtml: document.getElementById('hr-priority-todos')?.innerHTML || '',
                    })"""
                )
                page.screenshot(
                    path=str(self.out_dir / "desktop-overview-diagnostic.png"),
                    full_page=True,
                )

                diagnostic = (
                    f"runtime={runtime_state}; page_errors={page_errors}; "
                    f"console_errors={console_errors}; api_failures={api_failures}; "
                    f"static_failures={static_failures}"
                )
                self.assertTrue(runtime_state["apiClientScript"], diagnostic)
                self.assertTrue(runtime_state["overviewScript"], diagnostic)
                self.assertTrue(runtime_state["hasHrApi"], diagnostic)
                self.assertTrue(runtime_state["hasHrApiRequest"], diagnostic)
                self.assertEqual(page_errors, [], diagnostic)
                self.assertEqual(static_failures, [], diagnostic)
                self.assertEqual(api_failures, [], diagnostic)
                self.assertEqual(
                    page.locator(".hr-v2-conclusion .hr-skeleton").count(),
                    0,
                    diagnostic,
                )
                page.screenshot(
                    path=str(self.out_dir / "desktop-overview.png"),
                    full_page=True,
                )

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(
                    self.live_server_url + "/hr/overview",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    page.locator(".hr-v2-mobile-section-switcher").count(), 1
                )
                page.screenshot(
                    path=str(self.out_dir / "mobile-overview.png"), full_page=True
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "Browser page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            console_errors,
            [],
            "Browser console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            api_failures,
            [],
            "Canonical HR API failures: " + " | ".join(api_failures),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR static JS failures: " + " | ".join(static_failures),
        )

    def test_capture_hr09_v2_desktop_and_mobile(self):
        """Verify the real HR09 workspace uses the shared flat V2 shell."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        console_errors: list[str] = []
        static_failures: list[str] = []
        hr09_dir = self.out_dir.parent / "HR09-V2"
        hr09_dir.mkdir(parents=True, exist_ok=True)

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
                    if "/static/hr/css/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                response = page.goto(
                    self.live_server_url + "/hr/qualifications/",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR09']").count(), 1)
                self.assertEqual(page.locator(".hr09-process__step").count(), 5)
                self.assertEqual(page.locator(".hr09-nav a").count(), 6)
                self.assertEqual(page.locator(".hr09-hero").count(), 0)
                self.assertEqual(
                    page.locator(".hr09-primary-kpis .hr-v2-kpi").count(), 4
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
                    any("/hr/css/hr09-qualification.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertEqual(page_errors, [], diagnostic)
                self.assertEqual(static_failures, [], diagnostic)
                page.screenshot(
                    path=str(hr09_dir / "desktop-overview.png"),
                    full_page=True,
                )

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(
                    self.live_server_url + "/hr/qualifications/",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR09']").count(), 1)
                self.assertEqual(
                    page.locator(".hr-v2-mobile-section-switcher").count(), 1
                )
                page.screenshot(
                    path=str(hr09_dir / "mobile-overview.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "HR09 browser page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            console_errors,
            [],
            "HR09 browser console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR09 static CSS failures: " + " | ".join(static_failures),
        )

    def test_capture_hr12_v2_desktop_and_mobile(self):
        """Verify HR12 uses the shared V2 shell without hiding partial states."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        static_failures: list[str] = []
        hr12_dir = self.out_dir.parent / "HR12-V2"
        hr12_dir.mkdir(parents=True, exist_ok=True)
        routes = [
            "/hr/assessments/",
            "/hr/assessments/policies/",
            "/hr/assessments/goals/",
            "/hr/assessments/annual/",
            "/hr/assessments/term/",
            "/hr/assessments/ethics/",
            "/hr/assessments/review/",
            "/hr/assessments/archive/",
        ]

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

                def record_response(response):
                    if "/static/hr/css/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                response = page.goto(
                    self.live_server_url + routes[0],
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR12']").count(), 1)
                self.assertEqual(page.locator(".hr12-process__step").count(), 6)
                self.assertEqual(page.locator(".hr12-nav a").count(), 8)
                self.assertEqual(page.locator(".hr12-hero").count(), 0)
                self.assertEqual(
                    page.locator(".hr12-primary-kpis .hr-v2-kpi").count(), 4
                )
                self.assertNotEqual(
                    page.locator("#sourceHealth").inner_text().strip(),
                    "读取中",
                    "HR12 boot did not settle after network idle",
                )

                loaded_styles = page.evaluate(
                    """() => Array.from(document.styleSheets)
                      .map((sheet) => sheet.href || '')
                      .filter(Boolean)"""
                )
                diagnostic = (
                    f"styles={loaded_styles}; page_errors={page_errors}; "
                    f"static_failures={static_failures}"
                )
                self.assertTrue(
                    any("/hr/css/hr-v2.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertTrue(
                    any("/hr/css/hr12-assessment.css" in href for href in loaded_styles),
                    diagnostic,
                )
                self.assertEqual(page_errors, [], diagnostic)
                self.assertEqual(static_failures, [], diagnostic)
                page.screenshot(
                    path=str(hr12_dir / "desktop-overview.png"),
                    full_page=True,
                )

                for route in routes[1:]:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, f"No HTTP response for HR12 {route}")
                    self.assertEqual(
                        response.status,
                        200,
                        f"HR12 {route} returned HTTP {response.status}",
                    )
                    self.assertEqual(
                        page.locator("[data-module='HR12']").count(),
                        1,
                        f"HR12 V2 shell missing at {route}",
                    )

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(
                    self.live_server_url + routes[0],
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR12']").count(), 1)
                self.assertEqual(
                    page.locator(".hr-v2-mobile-section-switcher").count(), 1
                )
                page.screenshot(
                    path=str(hr12_dir / "mobile-overview.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "HR12 browser page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR12 static CSS failures: " + " | ".join(static_failures),
        )
