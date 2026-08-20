"""Real Chromium click-flow acceptance for the HR application.

This suite deliberately exercises the running Django application in a browser.
It does not replace request/API unit tests: it proves that a user can submit the
real login form and that HR13-HR18 workspace navigation works through actual DOM
clicks while the pages execute their production JavaScript and canonical HR API
requests.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import skipUnless
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


MODULES = {
    "hr_title": {
        "code": "HR13",
        "routes": [
            "/hr/titles/",
            "/hr/titles/applications/",
            "/hr/titles/eligibility/",
            "/hr/titles/materials/",
            "/hr/titles/experts/",
            "/hr/titles/deliberation/",
            "/hr/titles/publicity/",
            "/hr/titles/appeals/",
            "/hr/titles/results/",
        ],
    },
    "hr_appointment": {
        "code": "HR14",
        "routes": [
            "/hr/appointments/",
            "/hr/appointments/policies/",
            "/hr/appointments/quota/",
            "/hr/appointments/competitions/",
            "/hr/appointments/applications/",
            "/hr/appointments/ranking/",
            "/hr/appointments/publicity/",
            "/hr/appointments/appointments/",
            "/hr/appointments/term-changes/",
        ],
    },
    "hr_payroll": {
        "code": "HR15",
        "routes": [
            "/hr/payroll/",
            "/hr/payroll/profiles/",
            "/hr/payroll/periods/",
            "/hr/payroll/calculations/",
            "/hr/payroll/rules/",
            "/hr/payroll/allowances/",
            "/hr/payroll/social-security/",
            "/hr/payroll/results/",
            "/hr/payroll/payments/",
            "/hr/payroll/reconciliation/",
            "/hr/payroll/legacy-takeover/",
        ],
    },
    "hr_exit": {
        "code": "HR16",
        "routes": [
            "/hr/exit/",
            "/hr/exit/cases/",
            "/hr/exit/handover/",
            "/hr/exit/settlement/",
            "/hr/exit/retirement-precheck/",
            "/hr/exit/retirement-facts/",
            "/hr/exit/effects/",
            "/hr/exit/archive/",
        ],
    },
    "hr_self": {
        "code": "HR17",
        "routes": [
            "/hr/self/",
            "/hr/self/services/",
            "/hr/self/todos/",
            "/hr/self/progress/",
            "/hr/self/files/",
            "/hr/self/payslips/",
            "/hr/self/contracts/",
        ],
    },
    "hr_data": {
        "code": "HR18",
        "routes": [
            "/hr/data/",
            "/hr/data/metrics/",
            "/hr/data/population/",
            "/hr/data/as-of/",
            "/hr/data/quality/",
            "/hr/data/exchange/",
            "/hr/data/submissions/",
            "/hr/data/corrections/",
        ],
    },
}


@skipUnless(os.getenv("HR_BROWSER_FLOW") == "1", "browser flow is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-browser-media-"))
class HrBrowserFlowTests(StaticLiveServerTestCase):
    reset_sequences = True

    username = "hr-browser-auditor"
    password = "browser-flow-only-password"

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科浏览器验收学校",
            hq=True,
            address="长沙市浏览器验收路 1 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "browser-audit.png", b"browser-audit", content_type="image/png"
            ),
        )
        self.user = User.objects.create_superuser(
            username=self.username,
            email="browser-audit@example.invalid",
            password=self.password,
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="浏览器",
            employee_last_name="验收员",
            email="browser-employee@example.invalid",
            phone="13800000001",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=self.employee,
        )
        if work_info.company_id_id != self.company.pk:
            work_info.company_id = self.company
            work_info.save(update_fields=["company_id"])
        self._seed_self_identity_if_needed()

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

    def _seed_self_identity_if_needed(self):
        if not apps.is_installed("hr_self"):
            return
        from hr_staff.models import HrPerson, HrStaffMaster

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="浏览器验收员",
            status="ACTIVE",
        )
        HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="BROWSER-001",
            current_employment_status="ACTIVE",
            legacy_employee_id=self.employee.pk,
        )

    def _installed_targets(self):
        return [
            config
            for app_label, config in MODULES.items()
            if apps.is_installed(app_label)
        ]

    def test_real_login_form_submit_click(self):
        """Fill the production login form and submit it with a browser click."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for browser flow") from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                response = page.goto(
                    self.live_server_url + "/login/", wait_until="networkidle"
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.locator("#username").fill(self.username)
                page.locator("#password").fill(self.password)
                with page.expect_navigation(wait_until="networkidle"):
                    page.locator("button[type='submit']").click()

                self.assertNotEqual(
                    urlsplit(page.url).path,
                    "/login/",
                    "Real login form click returned to the login page",
                )
                session_cookies = [
                    cookie
                    for cookie in context.cookies()
                    if cookie["name"] == settings.SESSION_COOKIE_NAME
                ]
                self.assertTrue(session_cookies, "Login click did not establish a session")
                page.screenshot(
                    path=str(self.out_dir / "login-after-submit.png"), full_page=True
                )
                (self.out_dir / "login-evidence.json").write_text(
                    json.dumps(
                        {
                            "clicked": "button[type=submit]",
                            "final_url": page.url,
                            "session_cookie_present": True,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                context.close()
            finally:
                browser.close()

    def test_hr13_hr18_navigation_through_real_dom_clicks(self):
        """Run the app with MySQL and traverse each HR workspace by DOM click."""
        targets = self._installed_targets()
        self.assertTrue(targets, "No HR13-HR18 module is installed")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for browser flow") from exc

        page_errors: list[str] = []
        api_failures: list[str] = []
        click_evidence: list[dict[str, object]] = []

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

                for config in targets:
                    code = config["code"]
                    routes = config["routes"]
                    overview = routes[0]
                    response = page.goto(
                        self.live_server_url + overview, wait_until="networkidle"
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200, f"{code} overview is not runnable")
                    self.assertEqual(urlsplit(page.url).path, overview)

                    for route in routes[1:]:
                        selector = f'a[href="{route}"]'
                        link = page.locator(selector).first
                        self.assertGreater(
                            link.count(),
                            0,
                            f"{code} has no clickable DOM link for {route}",
                        )
                        link.scroll_into_view_if_needed()
                        with page.expect_navigation(wait_until="networkidle"):
                            link.click()
                        final_path = urlsplit(page.url).path
                        click_evidence.append(
                            {
                                "module": code,
                                "selector": selector,
                                "expected_path": route,
                                "final_path": final_path,
                            }
                        )
                        self.assertEqual(
                            final_path,
                            route,
                            f"{code} click {route} redirected to {page.url}",
                        )

                        home_selector = f'a[href="{overview}"]'
                        home_link = page.locator(home_selector).first
                        self.assertGreater(
                            home_link.count(),
                            0,
                            f"{code} page {route} cannot click back to overview",
                        )
                        with page.expect_navigation(wait_until="networkidle"):
                            home_link.click()
                        self.assertEqual(urlsplit(page.url).path, overview)

                    page.screenshot(
                        path=str(self.out_dir / f"{code}-after-click-journey.png"),
                        full_page=True,
                    )

                context.tracing.stop(path=str(self.out_dir / "real-click-trace.zip"))
                context.close()
            finally:
                browser.close()

        (self.out_dir / "click-evidence.json").write_text(
            json.dumps(click_evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.assertEqual(
            page_errors, [], "Browser page errors: " + " | ".join(page_errors)
        )
        self.assertEqual(
            api_failures, [], "Canonical HR API failures: " + " | ".join(api_failures)
        )
