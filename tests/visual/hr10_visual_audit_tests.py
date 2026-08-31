"""Real Chromium acceptance for the HR10 development V2 workspace."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr10VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster
        from hr10_development.models.learning_program import HrLearningProgram
        from hr10_development.models.plan import HrDevelopmentPlan
        from hr10_development.models.practice_project import HrEnterprisePracticeProject
        from hr10_development.models.provider_org import HrDevelopmentProviderOrganization
        from hr10_development.models.training_request import HrTrainingRequest

        self.company = Company.objects.create(
            company="跃科 HR10 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 10 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr10-visual.png", b"hr10-visual", content_type="image/png"),
        )
        self.user = get_user_model().objects.create_superuser(
            username="hr10-visual-auditor",
            email="hr10-visual@example.invalid",
            password="hr10-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR10",
            employee_last_name="视觉验收员",
            email="hr10-employee@example.invalid",
            phone="13800000010",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="周砺行",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="HR10-CLICK-001",
            legacy_employee_id=employee.pk,
            current_employment_status="ACTIVE",
        )
        self.provider = HrDevelopmentProviderOrganization.objects.create(
            tenant_id=self.company.pk,
            provider_code="HR10-PROVIDER-01",
            provider_kind="ENTERPRISE",
            legal_name="跃科智能制造实践基地",
            short_name="跃科实践基地",
            verification_status="VERIFIED",
        )
        HrDevelopmentPlan.objects.create(
            tenant_id=self.company.pk,
            plan_no="DEV-HR10-SEEDED",
            plan_type="INDIVIDUAL",
            staff_master_id=employee.pk,
            cycle_type="ANNUAL",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=180),
        )
        self.program = HrLearningProgram.objects.create(
            tenant_id=self.company.pk,
            program_code="TR-HR10-SEEDED",
            title="数智教学能力提升",
            activity_type="INTERNAL_TRAINING",
            provider_org_id=self.provider.id,
        )
        HrTrainingRequest.objects.create(
            tenant_id=self.company.pk,
            request_no="REQ-HR10-SEEDED",
            staff_master_id=employee.pk,
            request_type="INTERNAL_PROGRAM",
            program_id=self.program.id,
            reason="提升数智课程设计能力",
        )
        HrEnterprisePracticeProject.objects.create(
            tenant_id=self.company.pk,
            project_no="PRA-HR10-SEEDED",
            title="智能制造企业实践",
            specialty_category="智能制造",
            provider_org_id=self.provider.id,
            planned_start_date=date.today() + timedelta(days=30),
            planned_end_date=date.today() + timedelta(days=60),
            capacity=10,
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR10-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.routes = (
            ("dashboard", "/hr/development/dashboard"),
            ("plans", "/hr/development/plans"),
            ("programs", "/hr/development/programs"),
            ("requests", "/hr/development/requests"),
            ("practice", "/hr/development/enterprise-practice"),
            ("record", f"/hr/development/records/{employee.pk}"),
        )

    def browser_context(self, browser, viewport):
        context = browser.new_context(viewport=viewport, device_scale_factor=1)
        context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.session_cookie,
            "url": self.live_server_url,
        }])
        return context

    @staticmethod
    def monitor(page, page_errors, console_errors, api_failures, static_failures):
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("response", lambda response: api_failures.append(f"{response.status} {response.url}") if "/api/v1/hr/development" in response.url and response.status >= 400 else None)
        page.on("response", lambda response: static_failures.append(f"{response.status} {response.url}") if "/static/hr/" in response.url and response.status >= 400 else None)

    def test_capture_all_hr10_workspaces_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for mode, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
                    context = self.browser_context(browser, viewport)
                    page = context.new_page()
                    self.monitor(page, page_errors, console_errors, api_failures, static_failures)
                    for name, route in self.routes:
                        response = page.goto(self.live_server_url + route, wait_until="networkidle")
                        self.assertIsNotNone(response, route)
                        self.assertEqual(response.status, 200, route)
                        self.assertEqual(
                            page.locator(f'[data-module="HR10"][data-section="{name}"]').count(),
                            1,
                            f"{route} resolved to {page.url}; title={page.title()}; modules={page.locator('[data-module]').evaluate_all('(nodes) => nodes.map((node) => node.outerHTML.slice(0, 180))')}",
                        )
                        self.assertEqual(page.locator(".hr10-nav a, .hr10-nav span.disabled").count(), 6, route)
                        self.assertEqual(page.locator(".hr-v2-pagehead").count(), 1, route)
                        if name in {"plans", "programs", "requests", "practice"}:
                            page.locator(".hr10-panel").wait_for(state="visible", timeout=10000)
                        if mode == "mobile":
                            self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1, route)
                        page.screenshot(path=str(self.out_dir / f"{mode}-{name}.png"), full_page=True)
                    context.close()
            finally:
                browser.close()
        self.assertEqual(page_errors, [], "HR10 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR10 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR10 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR10 static failures: " + " | ".join(static_failures))

    def test_real_browser_publishes_plan_and_program(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser, {"width": 1440, "height": 1000})
                page = context.new_page()
                self.monitor(page, page_errors, console_errors, api_failures, static_failures)

                page.goto(self.live_server_url + "/hr/development/plans", wait_until="networkidle")
                row = page.locator(".hr10-row").filter(has_text="DEV-HR10-SEEDED")
                row.get_by_role("button", name="完善目标").click()
                row.get_by_placeholder("本周期重点发展目标").fill("形成数智教学示范课程")
                row.get_by_placeholder("预期成果").fill("一门校级示范课")
                with page.expect_response(lambda response: "/versions" in response.url and response.request.method == "POST") as versioned:
                    row.get_by_role("button", name="保存目标版本").click()
                self.assertEqual(versioned.value.status, 201)
                page.wait_for_load_state("networkidle")
                row = page.locator(".hr10-row").filter(has_text="DEV-HR10-SEEDED")
                with page.expect_response(lambda response: response.url.endswith("/submit")) as submitted:
                    row.get_by_role("button", name="提交审核").click()
                self.assertEqual(submitted.value.status, 200)
                page.wait_for_load_state("networkidle")
                row = page.locator(".hr10-row").filter(has_text="DEV-HR10-SEEDED")
                with page.expect_response(lambda response: response.url.endswith("/approve")) as approved:
                    row.get_by_role("button", name="审核通过").click()
                self.assertEqual(approved.value.status, 200)
                page.wait_for_load_state("networkidle")
                row = page.locator(".hr10-row").filter(has_text="DEV-HR10-SEEDED")
                with page.expect_response(lambda response: response.url.endswith("/publish")) as published:
                    row.get_by_role("button", name="发布").click()
                self.assertEqual(published.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/development/programs", wait_until="networkidle")
                row = page.locator(".hr10-row").filter(has_text="数智教学能力提升")
                row.get_by_role("button", name="形成版本").click()
                row.get_by_placeholder("培训目标").fill("提升教师数智教学设计能力")
                row.get_by_placeholder("核心课程内容").fill("教学设计与课堂实践")
                with page.expect_response(lambda response: "/versions" in response.url and response.request.method == "POST") as program_versioned:
                    row.get_by_role("button", name="保存项目版本").click()
                self.assertEqual(program_versioned.value.status, 201)
                page.wait_for_load_state("networkidle")
                row = page.locator(".hr10-row").filter(has_text="数智教学能力提升")
                with page.expect_response(lambda response: response.url.endswith("/publish")) as program_published:
                    row.get_by_role("button", name="发布项目").click()
                self.assertEqual(program_published.value.status, 200)
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(self.out_dir / "desktop-real-actions-complete.png"), full_page=True)
                context.close()
            finally:
                browser.close()
        self.assertEqual(page_errors, [], "HR10 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR10 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR10 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR10 static failures: " + " | ".join(static_failures))
