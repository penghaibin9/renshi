"""Real-browser visual audit for HR13-HR18 child PRs.

CI runs this module explicitly with HR_VISUAL_AUDIT=1. The screenshots use a
real Django live server, MySQL test database, authenticated session, production
middleware and canonical workspace APIs. The fixture creates only the technical
identity needed to enter the application; it does not manufacture business KPI,
workflow or result rows for prettier screenshots.
"""

from __future__ import annotations

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
            ("overview", "/hr/titles/"),
            ("applications", "/hr/titles/applications/"),
            ("eligibility", "/hr/titles/eligibility/"),
            ("materials", "/hr/titles/materials/"),
            ("experts", "/hr/titles/experts/"),
            ("deliberation", "/hr/titles/deliberation/"),
            ("publicity", "/hr/titles/publicity/"),
            ("appeals", "/hr/titles/appeals/"),
            ("results", "/hr/titles/results/"),
        ],
    },
    "hr_appointment": {
        "code": "HR14",
        "routes": [
            ("overview", "/hr/appointments/"),
            ("policies", "/hr/appointments/policies/"),
            ("quota", "/hr/appointments/quota/"),
            ("competitions", "/hr/appointments/competitions/"),
            ("applications", "/hr/appointments/applications/"),
            ("ranking", "/hr/appointments/ranking/"),
            ("publicity", "/hr/appointments/publicity/"),
            ("appointments", "/hr/appointments/appointments/"),
            ("term-changes", "/hr/appointments/term-changes/"),
        ],
    },
    "hr_payroll": {
        "code": "HR15",
        "routes": [
            ("overview", "/hr/payroll/"),
            ("profiles", "/hr/payroll/profiles/"),
            ("periods", "/hr/payroll/periods/"),
            ("calculations", "/hr/payroll/calculations/"),
            ("rules", "/hr/payroll/rules/"),
            ("allowances", "/hr/payroll/allowances/"),
            ("social-security", "/hr/payroll/social-security/"),
            ("results", "/hr/payroll/results/"),
            ("payments", "/hr/payroll/payments/"),
            ("reconciliation", "/hr/payroll/reconciliation/"),
            ("legacy-takeover", "/hr/payroll/legacy-takeover/"),
        ],
    },
    "hr_exit": {
        "code": "HR16",
        "routes": [
            ("overview", "/hr/exit/"),
            ("cases", "/hr/exit/cases/"),
            ("handover", "/hr/exit/handover/"),
            ("settlement", "/hr/exit/settlement/"),
            ("retirement-precheck", "/hr/exit/retirement-precheck/"),
            ("retirement-facts", "/hr/exit/retirement-facts/"),
            ("effects", "/hr/exit/effects/"),
            ("archive", "/hr/exit/archive/"),
        ],
    },
    "hr_self": {
        "code": "HR17",
        "routes": [
            ("overview", "/hr/self/"),
            ("services", "/hr/self/services/"),
            ("todos", "/hr/self/todos/"),
            ("progress", "/hr/self/progress/"),
            ("files", "/hr/self/files/"),
            ("payslips", "/hr/self/payslips/"),
            ("contracts", "/hr/self/contracts/"),
        ],
    },
    "hr_data": {
        "code": "HR18",
        "routes": [
            ("overview", "/hr/data/"),
            ("metrics", "/hr/data/metrics/"),
            ("population", "/hr/data/population/"),
            ("as-of", "/hr/data/as-of/"),
            ("quality", "/hr/data/quality/"),
            ("exchange", "/hr/data/exchange/"),
            ("submissions", "/hr/data/submissions/"),
            ("corrections", "/hr/data/corrections/"),
        ],
    },
}


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-visual-media-"))
class HrVisualAuditTests(StaticLiveServerTestCase):
    """Capture honest baseline screenshots through real middleware and APIs."""

    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 1 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "visual-audit.png", b"visual-audit", content_type="image/png"
            ),
        )
        self.user = User.objects.create_superuser(
            username="hr-visual-auditor",
            email="visual-audit@example.invalid",
            password="visual-audit-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="视觉",
            employee_last_name="验收员",
            email="visual-employee@example.invalid",
            phone="13800000000",
            is_active=True,
        )
        # Employee creation signals may already create the one-to-one work-info
        # row before a request tenant exists. The production company manager is
        # intentionally fail-closed in that state, so use Django's base manager
        # only to locate this lifecycle-owned technical row. Page/API reads still
        # go through the real tenant-aware managers and middleware below.
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
            os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _seed_self_identity_if_needed(self):
        """Create only the login-to-HR03 identity bridge required by HR17."""
        if not apps.is_installed("hr_self"):
            return
        from hr_staff.models import HrPerson, HrStaffMaster

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="视觉验收员",
            status="ACTIVE",
        )
        HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="VISUAL-001",
            current_employment_status="ACTIVE",
            legacy_employee_id=self.employee.pk,
        )

    def _installed_targets(self):
        return [
            (app_label, config)
            for app_label, config in MODULES.items()
            if apps.is_installed(app_label)
        ]

    def test_capture_real_workspace_screenshots(self):
        """Keep Playwright entirely inside the test body.

        Django ORM setup/teardown runs outside Playwright's sync event-loop
        context, so Django's SynchronousOnlyOperation protection remains active
        instead of being bypassed with DJANGO_ALLOW_ASYNC_UNSAFE.
        """
        targets = self._installed_targets()
        self.assertTrue(
            targets, "No HR13-HR18 child module is installed in this PR merge state"
        )

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
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_api_failure)

                for _app_label, config in targets:
                    code = config["code"]
                    module_dir = self.out_dir / code
                    module_dir.mkdir(parents=True, exist_ok=True)
                    for slug, route in config["routes"]:
                        response = page.goto(
                            self.live_server_url + route, wait_until="networkidle"
                        )
                        self.assertIsNotNone(
                            response, f"No HTTP response for {code} {route}"
                        )
                        self.assertEqual(
                            response.status,
                            200,
                            f"{code} {route} returned HTTP {response.status}",
                        )
                        self.assertEqual(
                            urlsplit(page.url).path,
                            route,
                            f"{code} {route} redirected to {page.url}",
                        )
                        page.screenshot(
                            path=str(module_dir / f"desktop-{slug}.png"),
                            full_page=True,
                        )

                    overview = config["routes"][0][1]
                    page.set_viewport_size({"width": 390, "height": 844})
                    response = page.goto(
                        self.live_server_url + overview, wait_until="networkidle"
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        urlsplit(page.url).path,
                        overview,
                        f"{code} mobile overview redirected to {page.url}",
                    )
                    page.screenshot(
                        path=str(module_dir / "mobile-overview.png"), full_page=True
                    )
                    page.set_viewport_size({"width": 1440, "height": 1000})

                context.close()
            finally:
                browser.close()

        self.assertEqual(
            page_errors, [], "Browser page errors: " + " | ".join(page_errors)
        )
        self.assertEqual(
            api_failures, [], "Canonical HR API failures: " + " | ".join(api_failures)
        )
