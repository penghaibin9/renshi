"""Real Chromium acceptance for the HR15 payroll V2 workspace."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr15-visual-media-"))
class Hr15VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    routes = [
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
    ]

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
        from hr_staff.models import HrPerson, HrStaffMaster

        self.company = Company.objects.create(
            company="跃科 HR15 视觉验收学校", hq=True, address="长沙市薪酬路 15 号",
            country="CN", state="Hunan", city="Changsha", zip="410000",
            icon=SimpleUploadedFile("hr15.png", b"hr15", content_type="image/png"),
        )
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="hr15-visual-auditor", email="hr15-visual@example.invalid",
            password="hr15-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user, employee_first_name="HR15", employee_last_name="视觉验收员",
            email="hr15-employee@example.invalid", phone="13800000015", is_active=True,
        )
        work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        if work.company_id_id != self.company.pk:
            work.company_id = self.company
            work.save(update_fields=["company_id"])

        self.person = HrPerson.objects.create(
            tenant_id=self.company.pk, legal_name="薪酬视觉验收员"
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk, person_id=self.person,
            staff_no="HR15-VISUAL-0015", legacy_employee_id=self.employee.pk,
        )

        self.profile = PayrollProfile.objects.create(
            tenant_id=self.company.pk, staff_id=self.staff.id,
            payroll_identity_no="PAY-2026-0015", pay_group_code="FACULTY",
            currency_code="CNY", effective_from=date(2026, 1, 1), status="ACTIVE",
        )
        self.period = PayrollPeriod.objects.create(
            tenant_id=self.company.pk, period_code="2026-08", start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31), status="FINALIZED",
        )
        self.source_result = PayrollResultFact.objects.create(
            tenant_id=self.company.pk, result_no="PAY-2026-08-0015",
            payroll_period_id=self.period.id, staff_id=self.staff.id, currency_code="CNY",
            gross_amount=Decimal("12000.00"), deduction_amount=Decimal("2200.00"),
            net_amount=Decimal("9800.00"), status="FINALIZED",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR15-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_all_routes_and_append_real_adjustment(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors = []
        console_errors = []
        static_failures = []
        api_failures = []
        adjustment_no = "PAY-2026-08-0015-补差-01"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.session_cookie, "url": self.live_server_url}])
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

                def track_response(response):
                    if "/static/hr/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")
                    if "/api/v1/hr/payroll/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", track_response)
                for slug, route in self.routes:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200, f"HR15 {route} returned HTTP {response.status}")
                    self.assertEqual(page.locator("[data-module='HR15']").count(), 1)
                    self.assertEqual(page.locator(".hr15-nav a").count(), 11)
                    self.assertEqual(page.locator("#hr15-kpis .hr15-kpi").count(), 6)
                    if slug == "overview":
                        self.assertEqual(page.locator(".hr15-process__step").count(), 6)
                    if slug == "results":
                        self.assertEqual(page.locator(".hr15-adjust-card").count(), 1)
                    if slug == "legacy-takeover":
                        self.assertEqual(page.locator("#hr15-legacy-reconcile").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"desktop-{slug}.png"), full_page=True)

                response = page.goto(self.live_server_url + "/hr/payroll/results/", wait_until="networkidle")
                self.assertEqual(response.status, 200)
                page.locator("[data-open]").first.click()
                form = page.locator(".hr15-adjust-form.open")
                form.locator('[name="adjustmentNo"]').fill(adjustment_no)
                form.locator('[name="grossDelta"]').fill("120.00")
                form.locator('[name="deductionDelta"]').fill("20.00")
                self.assertEqual(form.locator('[name="netDelta"]').input_value(), "100.00")
                with page.expect_response(lambda item: "/adjustments/" in item.url and item.request.method == "POST") as response_info:
                    form.locator('[type="submit"]').click()
                self.assertEqual(response_info.value.status, 201)
                page.locator("#hr15-adjust-result.ok").wait_for(state="visible")
                self.assertIn("已追加", page.locator("#hr15-adjust-result").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-results-adjusted.png"), full_page=True)

                page.set_viewport_size({"width": 390, "height": 844})
                for slug, route in self.routes:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                    page.screenshot(path=str(self.out_dir / f"mobile-{slug}.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_payroll.models import PayrollResultFact
        adjustment = PayrollResultFact.objects.get(tenant_id=self.company.pk, result_no=adjustment_no)
        self.assertEqual(adjustment.status, "ADJUSTED")
        self.assertEqual(adjustment.supersedes_result_id, self.source_result.id)
        self.assertEqual(adjustment.gross_amount, Decimal("120.00"))
        self.assertEqual(adjustment.deduction_amount, Decimal("20.00"))
        self.assertEqual(adjustment.net_amount, Decimal("100.00"))
        self.assertTrue(PayrollResultFact.objects.filter(pk=self.source_result.pk, net_amount=Decimal("9800.00")).exists())
        self.assertEqual(page_errors, [], "HR15 browser page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR15 browser console errors: " + " | ".join(console_errors))
        self.assertEqual(static_failures, [], "HR15 HR static failures: " + " | ".join(static_failures))
        self.assertEqual(api_failures, [], "HR15 payroll API failures: " + " | ".join(api_failures))
