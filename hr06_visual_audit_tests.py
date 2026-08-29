"""Real Chromium acceptance for HR06 V2 personnel-change workspaces.

Only the technical school/user identity is created. The test deliberately
creates no personnel-change cases or temporary-assignment business rows, so
empty states, tenant fail-closed behavior, canonical bootstrap reads and the
shared V2 shell are validated without manufacturing product data.
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
class Hr06VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    ROUTES = (
        ("center", "/hr/changes/", None, None),
        ("new", "/hr/changes/new", "hr06-bootstrap-state", "正在读取 HR06"),
        ("future", "/hr/changes/future", None, None),
        ("transfers", "/hr/changes/transfers", None, None),
        ("identity", "/hr/changes/job-identity", None, None),
        ("secondments", "/hr/changes/secondments", None, None),
        ("ledger", "/hr/changes/ledger", None, None),
    )

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR06 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 6 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr06-visual.png",
                b"hr06-visual",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr06-visual-auditor",
            email="hr06-visual@example.invalid",
            password="hr06-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR06",
            employee_last_name="视觉验收员",
            email="hr06-employee@example.invalid",
            phone="13800000006",
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
        ) / "HR06-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_primary_hr06_workspaces_desktop_and_mobile(self):
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
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/" in response.url and response.status >= 400:
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
                            f'[data-module="HR06"][data-section="{section}"]'
                        ).count(),
                        1,
                        route,
                    )
                    self.assertEqual(page.locator(".hr06-nav a").count(), 7, route)
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
                    self.assertEqual(page.locator(".hr06-nav a").count(), 7, route)
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

        self.assertEqual(page_errors, [], "HR06 page errors: " + " | ".join(page_errors))
        self.assertEqual(
            console_errors,
            [],
            "HR06 console errors: " + " | ".join(console_errors),
        )
        self.assertEqual(
            api_failures,
            [],
            "HR06 canonical API failures: " + " | ".join(api_failures),
        )
        self.assertEqual(
            static_failures,
            [],
            "HR06 static resource failures: " + " | ".join(static_failures),
        )
