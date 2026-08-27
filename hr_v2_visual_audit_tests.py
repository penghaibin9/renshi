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
    """Capture the real HR01 V2 page at desktop and mobile widths."""

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
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")
        ) / "HR01-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr01_v2_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
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

                def record_api_failure(response):
                    if (
                        "/api/hr/v1/" in response.url
                        or "/api/v1/hr/" in response.url
                    ) and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_api_failure)

                response = page.goto(
                    self.live_server_url + "/hr/overview",
                    wait_until="networkidle",
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR01']").count(), 1)
                self.assertEqual(page.locator(".hr-home__module").count(), 18)
                self.assertEqual(page.locator(".hr-v2-conclusion").count(), 3)
                self.assertEqual(page.locator(".hr-v2-conclusion .hr-skeleton").count(), 0)
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
                    path=str(self.out_dir / "mobile-overview.png"),
                    full_page=True,
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
            api_failures,
            [],
            "Canonical HR API failures: " + " | ".join(api_failures),
        )
