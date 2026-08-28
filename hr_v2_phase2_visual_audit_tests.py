"""Focused real-browser acceptance for HR UI V2 phase 2 (HR02/HR03).

The fixture creates only the technical school/user/person identity required to
enter the production pages. It does not manufacture organization capacity,
quality issues, qualifications, materials or correction cases for prettier
screenshots; honest empty states are part of the acceptance contract.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-v2-phase2-media-"))
class HrV2Phase2VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR V2 二阶段视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 3 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr-v2-phase2.png",
                b"hr-v2-phase2",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr-v2-phase2-auditor",
            email="hr-v2-phase2@example.invalid",
            password="hr-v2-phase2-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])

        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="二阶段",
            employee_last_name="视觉验收员",
            email="hr-v2-phase2-employee@example.invalid",
            phone="13800000005",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=self.employee,
        )
        if work_info.company_id_id != self.company.pk:
            work_info.company_id = self.company
            work_info.save(update_fields=["company_id"])

        self.person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="二阶段视觉验收员",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            staff_no="V2-PHASE2-001",
            current_employment_status="ACTIVE",
            legacy_employee_id=self.employee.pk,
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value

        self.out_dir = Path(
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _browser_context(self, browser, width=1440, height=1000):
        context = browser.new_context(
            viewport={"width": width, "height": height},
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
        return context

    def _assert_route(self, page, route):
        response = page.goto(self.live_server_url + route, wait_until="networkidle")
        self.assertIsNotNone(response, f"No HTTP response for {route}")
        self.assertEqual(response.status, 200, f"{route} returned HTTP {response.status}")
        self.assertEqual(
            urlsplit(page.url).path,
            route,
            f"{route} redirected to {page.url}",
        )
        return response

    def test_hr02_real_v2_workspaces_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        api_failures: list[str] = []
        routes = [
            ("organizations", "/hr/structure/organizations"),
            ("relations", "/hr/structure/relations"),
            ("staffing-plans", "/hr/structure/staffing-plans"),
            ("post-catalogs", "/hr/structure/post-catalogs"),
            ("positions", "/hr/structure/positions"),
            ("history", "/hr/structure/history"),
        ]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                def record_failure(response):
                    if "/api/hr/v1/structure/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_failure)
                module_dir = self.out_dir / "HR02-V2"
                module_dir.mkdir(parents=True, exist_ok=True)

                for slug, route in routes:
                    self._assert_route(page, route)
                    self.assertEqual(page.locator("[data-module='HR02']").count(), 1)
                    self.assertEqual(page.locator(".hr02-nav").count(), 1)
                    self.assertEqual(page.locator(".hr02-nav a").count(), 6)
                    self.assertEqual(page.locator(".hr02-hero").count(), 0)
                    page.screenshot(
                        path=str(module_dir / f"desktop-{slug}.png"),
                        full_page=True,
                    )

                self._assert_route(page, "/hr/structure/organizations")
                self.assertEqual(page.locator(".hr02-org-layout").count(), 1)
                self.assertEqual(page.locator("#hr-org-tree").count(), 1)
                self.assertEqual(page.locator("#hr-org-detail").count(), 1)
                self.assertEqual(page.locator("#hr02-control-summary").count(), 1)

                self._assert_route(page, "/hr/structure/positions")
                self.assertEqual(page.locator("#hr-position-summary").count(), 1)
                self.assertEqual(page.locator("#hr-position-table").count(), 1)

                page.set_viewport_size({"width": 390, "height": 844})
                self._assert_route(page, "/hr/structure/organizations")
                self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                page.screenshot(
                    path=str(module_dir / "mobile-organizations.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR02 browser page errors: " + " | ".join(page_errors))
        self.assertEqual(api_failures, [], "HR02 canonical API failures: " + " | ".join(api_failures))

    def test_hr03_real_v2_people_workspaces_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        api_failures: list[str] = []
        staff_id = str(self.staff.pk)
        routes = [
            ("list", "/hr/staff/"),
            ("profile", f"/hr/staff/{staff_id}/"),
            ("assignments", f"/hr/staff/{staff_id}/assignments"),
            ("backgrounds", f"/hr/staff/{staff_id}/backgrounds"),
            ("materials", f"/hr/staff/{staff_id}/materials"),
            ("corrections", f"/hr/staff/{staff_id}/corrections"),
            ("data-quality", "/hr/staff/data-quality/"),
        ]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                def record_failure(response):
                    if (
                        "/api/hr/v1/staff" in response.url
                        or "/api/hr/v1/corrections" in response.url
                    ) and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_failure)
                module_dir = self.out_dir / "HR03-V2"
                module_dir.mkdir(parents=True, exist_ok=True)

                for slug, route in routes:
                    self._assert_route(page, route)
                    self.assertEqual(page.locator("[data-module='HR03']").count(), 1)
                    page.screenshot(
                        path=str(module_dir / f"desktop-{slug}.png"),
                        full_page=True,
                    )

                self._assert_route(page, "/hr/staff/")
                self.assertEqual(page.locator(".hr03-panel").count(), 1)
                self.assertEqual(page.locator("#rows").count(), 1)
                self.assertGreaterEqual(page.locator("#rows tr").count(), 1)

                self._assert_route(page, f"/hr/staff/{staff_id}/")
                self.assertEqual(page.locator(".hr03-profile-head").count(), 1)
                self.assertEqual(page.locator(".hr03-profile-nav a").count(), 6)
                self.assertEqual(page.locator("#name").inner_text().strip(), "二阶段视觉验收员")

                page.set_viewport_size({"width": 390, "height": 844})
                self._assert_route(page, f"/hr/staff/{staff_id}/")
                self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                page.screenshot(
                    path=str(module_dir / "mobile-profile.png"),
                    full_page=True,
                )
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR03 browser page errors: " + " | ".join(page_errors))
        self.assertEqual(api_failures, [], "HR03 canonical API failures: " + " | ".join(api_failures))
