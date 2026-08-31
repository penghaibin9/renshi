"""Real Chromium acceptance for HR05 V2 onboarding workspaces.

The test seeds only the technical school/user identity required to open the
production pages. It deliberately creates no onboarding cases, materials,
tasks, or probation records: empty states must remain truthful and all
canonical HR05 reads must still complete without browser/API failures.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr05VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    ROUTES = (
        ("prehires", "/hr/onboarding/prehires", "hr05-prehire-list", "正在读取待报到人员"),
        ("reporting", "/hr/onboarding/reporting", "hr05-reporting-list", "正在读取报到对象"),
        ("materials", "/hr/onboarding/materials", None, None),
        ("collaboration", "/hr/onboarding/collaboration", None, None),
        ("probations", "/hr/onboarding/probations", "hr05-probation-list", "正在读取试用记录"),
    )

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR05 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 5 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr05-visual.png",
                b"hr05-visual",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr05-visual-auditor",
            email="hr05-visual@example.invalid",
            password="hr05-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR05",
            employee_last_name="视觉验收员",
            email="hr05-employee@example.invalid",
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
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")
        ) / "HR05-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_all_primary_hr05_workspaces_desktop_and_mobile(self):
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
                    if "/api/hr/v1/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")
                    if (
                        "/static/hr/" in response.url
                        and response.status >= 400
                    ):
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)

                for section, route, settle_id, loading_text in self.ROUTES:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(
                        page.locator(
                            f'[data-module="HR05"][data-section="{section}"]'
                        ).count(),
                        1,
                        route,
                    )
                    self.assertEqual(page.locator(".hr05-nav a").count(), 5, route)
                    if settle_id and loading_text:
                        page.wait_for_function(
                            """([id, text]) => {
                              const host = document.getElementById(id);
                              return host && !host.textContent.includes(text);
                            }""",
                            arg=[settle_id, loading_text],
                            timeout=8000,
                        )
                    page.screenshot(
                        path=str(self.out_dir / f"desktop-{section}.png"),
                        full_page=True,
                    )

                page.set_viewport_size({"width": 390, "height": 844})
                for section, route, settle_id, loading_text in self.ROUTES:
                    response = page.goto(
                        self.live_server_url + route,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(
                        page.locator(".hr-v2-mobile-section-switcher").count(),
                        1,
                        route,
                    )
                    if settle_id and loading_text:
                        page.wait_for_function(
                            """([id, text]) => {
                              const host = document.getElementById(id);
                              return host && !host.textContent.includes(text);
                            }""",
                            arg=[settle_id, loading_text],
                            timeout=8000,
                        )
                    page.screenshot(
                        path=str(self.out_dir / f"mobile-{section}.png"),
                        full_page=True,
                    )
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR05 page errors: " + " | ".join(page_errors))
        self.assertEqual(
            console_errors,
            [],
            "HR05 console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            api_failures,
            [],
            "HR05 canonical API failures: " + " | ".join(api_failures),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR05 static resource failures: " + " | ".join(static_failures),
        )
