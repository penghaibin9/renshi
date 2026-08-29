"""Focused Chromium regression contract for the shared HR V2 shell.

The broad visual suites prove page-level rendering. This file protects the two
shared shell invariants that previously regressed because theme CSS loaded after
HR V2 CSS: narrow-screen sidebar geometry and duplicate breadcrumb visibility.
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
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-v2-shell-media-"))
class HrV2ShellRegressionTests(StaticLiveServerTestCase):
    """Lock shared desktop/mobile shell behavior with real Chromium geometry."""

    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR V2 壳层回归学校",
            hq=True,
            address="长沙市壳层回归路 1 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr-v2-shell.png",
                b"hr-v2-shell",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr-v2-shell-auditor",
            email="hr-v2-shell@example.invalid",
            password="hr-v2-shell-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])

        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="V2",
            employee_last_name="壳层回归员",
            email="hr-v2-shell-employee@example.invalid",
            phone="13800000005",
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
        ) / "HR-V2-SHELL"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_shared_shell_geometry_and_breadcrumb_contract(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        console_errors: list[str] = []

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

                response = page.goto(
                    self.live_server_url + "/hr/overview",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR01']").count(), 1)

                desktop = page.evaluate(
                    """() => {
                      const sidebar = document.getElementById('sidebar');
                      const breadcrumbs = document.getElementById('breadcrumbs-container');
                      return {
                        sidebarWidth: sidebar ? sidebar.getBoundingClientRect().width : null,
                        breadcrumbDisplay: breadcrumbs ? getComputedStyle(breadcrumbs).display : null,
                      };
                    }"""
                )
                self.assertIsNotNone(desktop["sidebarWidth"])
                self.assertGreaterEqual(desktop["sidebarWidth"], 200)
                self.assertNotEqual(desktop["breadcrumbDisplay"], "none")

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

                mobile = page.evaluate(
                    """() => {
                      const sidebar = document.getElementById('sidebar');
                      const main = document.querySelector('.oh-main-content');
                      const header = document.querySelector('.oh-main-header');
                      const pin = document.getElementById('sidebarPinBtn');
                      const breadcrumbs = document.getElementById('breadcrumbs-container');
                      return {
                        sidebarWidth: sidebar ? sidebar.getBoundingClientRect().width : null,
                        mainMarginLeft: main ? parseFloat(getComputedStyle(main).marginLeft) : null,
                        headerLeft: header ? parseFloat(getComputedStyle(header).left) : null,
                        pinDisplay: pin ? getComputedStyle(pin).display : null,
                        breadcrumbDisplay: breadcrumbs ? getComputedStyle(breadcrumbs).display : null,
                      };
                    }"""
                )
                diagnostic = f"mobile shell state={mobile}"
                self.assertIsNotNone(mobile["sidebarWidth"], diagnostic)
                self.assertAlmostEqual(mobile["sidebarWidth"], 64.0, delta=1.0, msg=diagnostic)
                self.assertAlmostEqual(mobile["mainMarginLeft"], 64.0, delta=1.0, msg=diagnostic)
                self.assertAlmostEqual(mobile["headerLeft"], 64.0, delta=1.0, msg=diagnostic)
                self.assertEqual(mobile["pinDisplay"], "none", diagnostic)
                self.assertEqual(mobile["breadcrumbDisplay"], "none", diagnostic)

                page.screenshot(
                    path=str(self.out_dir / "mobile-shell-contract.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors,
            [],
            "HR V2 shell page errors: " + " | ".join(page_errors),
        )
        self.assertEqual(
            console_errors,
            [],
            "HR V2 shell console errors: " + " | ".join(console_errors),
        )
