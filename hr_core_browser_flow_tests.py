"""Focused real-browser click journeys for HR01-HR12.

The test runs against Django's live server and MySQL in GitHub Actions. It enters
an actual module workspace, locates the real rendered navigation anchor and
clicks it with Chromium. Missing links, redirects, server errors, page JS errors
and canonical HR API failures are acceptance failures rather than request-only
smoke checks.
"""

from __future__ import annotations

import json
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


JOURNEYS = [
    ("HR01", "/hr/overview", "/hr/todos"),
    ("HR02", "/hr/structure/organizations", "/hr/structure/positions"),
    ("HR03", "/hr/staff/", "/hr/staff/data-quality/"),
    ("HR04", "/hr/recruitment/campaigns", "/hr/recruitment/candidates"),
    ("HR05", "/hr/onboarding/prehires", "/hr/onboarding/reporting"),
    ("HR06", "/hr/changes/", "/hr/changes/transfers"),
    ("HR07", "/hr/contracts/", "/hr/contracts/risks/"),
    ("HR08", "/hr/external-teachers/", "/hr/external-teachers/industry/"),
    ("HR09", "/hr/qualifications/", "/hr/qualifications/credentials/"),
    ("HR10", "/hr/development/dashboard", "/hr/development/plans"),
    ("HR11", "/hr/time/", "/hr/time/attendance/"),
    ("HR12", "/hr/assessments/", "/hr/assessments/policies/"),
]


@skipUnless(os.getenv("HR_BROWSER_FLOW") == "1", "browser flow is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-core-browser-media-"))
class HrCoreBrowserFlowTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科核心流程验收学校",
            hq=True,
            address="长沙市核心流程验收路 1 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "core-browser-audit.png",
                b"core-browser-audit",
                content_type="image/png",
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr-core-browser-auditor",
            email="core-browser-audit@example.invalid",
            password="core-browser-flow-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="核心流程",
            employee_last_name="验收员",
            email="core-browser-employee@example.invalid",
            phone="13800000002",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=self.employee,
        )
        if work_info.company_id_id != self.company.pk:
            work_info.company_id = self.company
            work_info.save(update_fields=["company_id"])

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="核心流程验收员",
            status="ACTIVE",
        )
        HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="CORE-BROWSER-001",
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
            os.getenv("HR_BROWSER_ARTIFACT_DIR", "artifacts/hr-browser-flow")
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_hr01_hr12_real_navigation_clicks(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for browser flow") from exc

        page_errors: list[str] = []
        api_failures: list[str] = []
        evidence: list[dict[str, object]] = []

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
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                def record_api_failure(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_api_failure)

                for code, start_path, target_path in JOURNEYS:
                    response = page.goto(
                        self.live_server_url + start_path,
                        wait_until="networkidle",
                    )
                    self.assertIsNotNone(response, f"{code} start returned no response")
                    self.assertEqual(
                        response.status,
                        200,
                        f"{code} start {start_path} returned HTTP {response.status}",
                    )
                    self.assertEqual(
                        urlsplit(page.url).path,
                        start_path,
                        f"{code} start redirected to {page.url}",
                    )

                    selector = f'a[href="{target_path}"]'
                    link = page.locator(selector).first
                    self.assertGreater(
                        link.count(),
                        0,
                        f"{code} rendered no clickable link for {target_path}",
                    )
                    link.scroll_into_view_if_needed()
                    with page.expect_navigation(wait_until="networkidle"):
                        link.click()

                    final_path = urlsplit(page.url).path
                    evidence.append(
                        {
                            "module": code,
                            "start_path": start_path,
                            "selector": selector,
                            "expected_path": target_path,
                            "final_path": final_path,
                        }
                    )
                    self.assertEqual(
                        final_path,
                        target_path,
                        f"{code} click redirected to {page.url}",
                    )
                    page.screenshot(
                        path=str(self.out_dir / f"{code}-core-click.png"),
                        full_page=True,
                    )

                context.tracing.stop(
                    path=str(self.out_dir / "hr01-hr12-real-click-trace.zip")
                )
                context.close()
            finally:
                browser.close()

        (self.out_dir / "hr01-hr12-click-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
