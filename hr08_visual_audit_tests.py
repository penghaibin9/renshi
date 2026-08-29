"""Real Chromium acceptance for the HR08 V2 external-workforce workspace."""

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
class Hr08VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_external.models import (
            HrExternalContribution,
            HrExternalEngagement,
            HrExternalExitCase,
            HrExternalHiringCase,
            HrExternalIndustryProfile,
            HrExternalRenewalReview,
            HrExternalServiceTask,
            HrExternalTeacherProfile,
            HrExternalWorkspace,
        )
        from hr_external.services.category_service import CategoryService
        from hr_staff.tests.factories import make_org, make_person
        from hr_structure.models import HrOrganizationVersion

        self.company = Company.objects.create(
            company="跃科 HR08 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 8 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr08-visual.png", b"hr08-visual", content_type="image/png"),
        )
        self.user = get_user_model().objects.create_superuser(
            username="hr08-visual-auditor",
            email="hr08-visual@example.invalid",
            password="hr08-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR08",
            employee_last_name="视觉验收员",
            email="hr08-employee@example.invalid",
            phone="13800000008",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        tenant_id = self.company.pk
        root_org = make_org(tenant_id, "HR08-SCHOOL", "跃科视觉验收学校", date(2020, 1, 1), org_type="SCHOOL")
        host_org = make_org(tenant_id, "HR08-COLLEGE", "智能制造学院", date(2020, 1, 1))
        HrOrganizationVersion.objects.filter(organization_id=host_org).update(parent_organization_id=root_org)
        self.host_org = host_org

        CategoryService().ensure_default_categories(tenant_id)
        from hr_external.models import HrExternalCategory

        category = HrExternalCategory.objects.get(tenant_id=tenant_id, code="INDUSTRY_PROFESSOR")
        person = make_person(tenant_id, "周明远")
        self.profile = HrExternalTeacherProfile.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            external_teacher_no="EXT-CLICK-08001",
            primary_category=category,
            source_organization_name="远景智能研究院",
            source_position_title="首席工程师",
            industry_domain="智能制造",
            expertise_tags=["工业机器人", "产线规划"],
            highest_professional_title="正高级工程师",
            candidate_pool_status="ENGAGED",
            current_engagement_status="ACTIVE",
            ethics_status="PASS",
            identity_verification_status="VERIFIED",
        )
        HrExternalIndustryProfile.objects.create(
            tenant_id=tenant_id,
            profile_id=self.profile,
            industry_experience_years=18,
            current_employer="远景智能研究院",
            current_industry_role="首席工程师",
            major_projects=["柔性产线升级"],
            patents_products=["智能调度平台"],
            technical_awards=["省技术进步奖"],
            industry_domains=["智能制造"],
            skills=["工业机器人", "数字孪生"],
        )
        today = date.today()
        self.engagement = HrExternalEngagement.objects.create(
            tenant_id=tenant_id,
            engagement_no="ENG-CLICK-08001",
            person_id=person,
            external_profile_id=self.profile,
            category_id=category,
            purpose="承担企业实践教学与专业建设",
            host_organization_id=host_org.id,
            start_at=today - timedelta(days=120),
            end_at=today + timedelta(days=245),
            status="ACTIVE",
            agreement_status="ACTIVE",
        )
        HrExternalContribution.objects.create(
            tenant_id=tenant_id,
            engagement_id=self.engagement,
            contribution_type="COURSE_CO_BUILD",
            title="智能产线实践课程共建",
            period="2026 春季",
            verification_status="VERIFIED",
            status="VERIFIED",
        )
        HrExternalWorkspace.objects.create(
            tenant_id=tenant_id,
            name="智能制造产业工作室",
            workspace_type="INDUSTRY_TEACHING_WORKSHOP",
            leader_engagement_id=self.engagement,
            organization_id=host_org.id,
            start_at=today - timedelta(days=90),
            status="ACTIVE",
        )
        self.hiring_case = HrExternalHiringCase.objects.create(
            tenant_id=tenant_id,
            case_no="HIRE-CLICK-08001",
            request_org_id=host_org.id,
            requester_id=self.user.id,
            category_id=category,
            purpose="承担秋季企业实践指导",
            proposed_person_id=person,
            requested_start=today + timedelta(days=30),
            requested_end=today + timedelta(days=395),
            planned_assignments_json=[{"summary": "企业实践指导"}],
            status="DRAFT",
        )
        HrExternalServiceTask.objects.create(
            tenant_id=tenant_id,
            engagement_id=self.engagement,
            task_type="PRACTICE_GUIDANCE",
            source_domain="HR08",
            title="2026 秋季企业实践指导",
            planned_quantity=32,
            planned_unit="课时",
            planned_start=today,
            planned_end=today + timedelta(days=120),
            owner_org_id=host_org.id,
            status="ASSIGNED",
        )
        HrExternalRenewalReview.objects.create(
            tenant_id=tenant_id,
            engagement_id=self.engagement,
            review_due_at=today + timedelta(days=180),
            status="DRAFT",
        )
        self.exit_case = HrExternalExitCase.objects.create(
            tenant_id=tenant_id,
            engagement_id=self.engagement,
            exit_reason="TERM_COMPLETED",
            planned_end_at=today + timedelta(days=245),
            status="PLANNED",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.routes = (
            ("home", "/hr/external-teachers/"),
            ("pool", "/hr/external-teachers/pool/"),
            ("profile", f"/hr/external-teachers/{self.profile.id}/"),
            ("industry", "/hr/external-teachers/industry/"),
            ("industry-detail", f"/hr/external-teachers/industry/{self.engagement.id}/"),
            ("hiring", "/hr/external-teachers/hiring/"),
            ("hiring-detail", f"/hr/external-teachers/hiring/{self.hiring_case.id}/"),
            ("tasks", "/hr/external-teachers/tasks/"),
            ("renewals", "/hr/external-teachers/renewals/"),
            ("exits", "/hr/external-teachers/exits/"),
        )
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")) / "HR08-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def browser_context(self, browser, viewport):
        context = browser.new_context(viewport=viewport, device_scale_factor=1)
        context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.session_cookie, "url": self.live_server_url}])
        return context

    def test_capture_all_hr08_workspaces_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for mode, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
                    context = self.browser_context(browser, viewport)
                    page = context.new_page()
                    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                    page.on("response", lambda response: api_failures.append(f"{response.status} {response.url}") if "/api/v1/hr/" in response.url and response.status >= 400 else None)
                    page.on("response", lambda response: static_failures.append(f"{response.status} {response.url}") if "/static/hr/" in response.url and response.status >= 400 else None)
                    for name, route in self.routes:
                        response = page.goto(self.live_server_url + route, wait_until="networkidle")
                        self.assertIsNotNone(response, route)
                        self.assertEqual(response.status, 200, route)
                        self.assertEqual(page.locator('[data-module="HR08"]').count(), 1, route)
                        self.assertEqual(page.locator(".hr08-nav a").count(), 7, route)
                        self.assertEqual(page.locator(".hr-v2-pagehead").count(), 1, route)
                        if mode == "mobile":
                            self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1, route)
                        page.screenshot(path=str(self.out_dir / f"{mode}-{name}.png"), full_page=True)
                    context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR08 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR08 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR08 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR08 static failures: " + " | ".join(static_failures))

    def test_real_browser_closes_task_renewal_and_exit_actions(self):
        from playwright.sync_api import sync_playwright

        from hr_external.models import (
            HrExternalExitCase,
            HrExternalHiringCase,
            HrExternalRenewalReview,
            HrExternalServiceTask,
        )

        page_errors, console_errors, api_failures = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser, {"width": 1440, "height": 1000})
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("response", lambda response: api_failures.append(f"{response.status} {response.url}") if "/api/v1/hr/" in response.url and response.status >= 400 else None)

                page.goto(self.live_server_url + f"/hr/external-teachers/hiring/{self.hiring_case.id}/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/submit") and response.request.method == "POST") as hiring_submit:
                    page.locator('[data-hiring-action="submit"]').click()
                self.assertEqual(hiring_submit.value.status, 200)
                page.wait_for_selector('[data-hiring-action="approve"]', timeout=10000)

                page.goto(self.live_server_url + "/hr/external-teachers/tasks/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/accept") and response.request.method == "POST") as accepted:
                    page.locator('[data-task-action="accept"]').first.click()
                self.assertEqual(accepted.value.status, 200)
                page.wait_for_selector('[data-task-action="start"]', timeout=10000)
                with page.expect_response(lambda response: response.url.endswith("/start") and response.request.method == "POST") as started:
                    page.locator('[data-task-action="start"]').first.click()
                self.assertEqual(started.value.status, 200)
                page.wait_for_selector('[data-task-action="submit"]', timeout=10000)
                with page.expect_response(lambda response: response.url.endswith("/submit") and response.request.method == "POST") as submitted:
                    page.locator('[data-task-action="submit"]').first.click()
                self.assertEqual(submitted.value.status, 200)
                page.wait_for_selector('[data-task-action="complete"]', timeout=10000)
                with page.expect_response(lambda response: response.url.endswith("/verify") and response.request.method == "POST") as verified:
                    page.locator('[data-task-action="complete"]').first.click()
                self.assertEqual(verified.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/external-teachers/renewals/", wait_until="networkidle")
                page.locator("[data-toggle-decision]").first.click()
                decision_form = page.locator("[data-decision-form]").first
                decision_form.locator('select[name="decision"]').select_option("DO_NOT_RENEW")
                with page.expect_response(lambda response: "/renewal-reviews/" in response.url and response.url.endswith("/decide")) as decided:
                    decision_form.locator('button[type="submit"]').click()
                self.assertEqual(decided.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/external-teachers/exits/", wait_until="networkidle")
                for expected_label in ("提交退出审核", "确认可退出"):
                    button = page.get_by_role("button", name=expected_label)
                    button.wait_for(state="visible", timeout=10000)
                    with page.expect_response(lambda response: response.url.endswith("/prepare") and response.request.method == "POST") as prepared:
                        button.click()
                    self.assertEqual(prepared.value.status, 200)
                    page.wait_for_load_state("networkidle")
                page.get_by_role("button", name="办理清退").click()
                with page.expect_response(lambda response: response.url.endswith("/complete") and response.request.method == "POST") as completed:
                    page.get_by_role("button", name="确认全部完成").click()
                self.assertEqual(completed.value.status, 200)
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(self.out_dir / "desktop-real-actions-complete.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.hiring_case.refresh_from_db()
        task = HrExternalServiceTask.objects.get(tenant_id=self.company.pk)
        renewal = HrExternalRenewalReview.objects.get(tenant_id=self.company.pk)
        exit_case = HrExternalExitCase.objects.get(tenant_id=self.company.pk)
        self.assertEqual(self.hiring_case.status, "SUBMITTED")
        self.assertEqual(task.status, "COMPLETED")
        self.assertEqual(renewal.decision, "DO_NOT_RENEW")
        self.assertEqual(exit_case.status, "CLOSED")
        self.assertEqual(page_errors, [], "HR08 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR08 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR08 API failures: " + " | ".join(api_failures))
