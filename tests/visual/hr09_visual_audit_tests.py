"""Real Chromium acceptance for the HR09 qualification V2 workspace."""

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
class Hr09VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True
    ROUTES = (
        ("overview", "/hr/qualifications/"),
        ("credentials", "/hr/qualifications/credentials/"),
        ("batches", "/hr/double-teacher/"),
        ("applications", "/hr/double-teacher/applications/"),
        ("recognitions", "/hr/double-teacher/recognitions/"),
        ("risks", "/hr/qualifications/risks/"),
    )

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_qualification.constants import RulePackVersionStatus
        from hr_qualification.models import (
            HrCredentialCatalogItem,
            HrDoubleTeacherRecognition,
            HrDoubleTeacherRecognitionBatch,
            HrDoubleTeacherRulePack,
            HrDoubleTeacherRulePackVersion,
            HrPersonCredential,
            HrQualificationRiskCase,
        )
        from hr_staff.models import HrPerson, HrStaffMaster

        self.company = Company.objects.create(
            company="跃科 HR09 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 9 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr09-visual.png", b"hr09-visual", content_type="image/png"),
        )
        self.user = get_user_model().objects.create_superuser(
            username="hr09-visual-auditor",
            email="hr09-visual@example.invalid",
            password="hr09-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR09",
            employee_last_name="视觉验收员",
            email="hr09-employee@example.invalid",
            phone="13800000009",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        self.person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="林知行",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            staff_no="HR09-CLICK-001",
            legacy_employee_id=employee.pk,
            current_employment_status="ACTIVE",
        )
        catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=self.company.pk,
            code="TEACHER-CERT-HR09",
            category="TEACHER_QUALIFICATION",
            name="高等学校教师资格证",
        )
        self.credential = HrPersonCredential.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            staff_master_id=self.staff,
            catalog_item_id=catalog,
            credential_name_snapshot=catalog.name,
            issuer_name="湖南省教育厅",
            valid_from=date.today() - timedelta(days=365),
            valid_to=date.today() + timedelta(days=730),
            status="DRAFT",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.company.pk,
            code="HR09-VISUAL-RULE",
            name="视觉验收双师认定规则",
        )
        self.rule_version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=date.today() - timedelta(days=30),
            status=RulePackVersionStatus.ACTIVE,
            checksum="hr09-visual-sealed-rule",
        )
        self.batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.company.pk,
            batch_no="HR09-BATCH-2026-01",
            name="2026 年双师型教师认定",
            school_year="2026-2027",
            application_start=date.today(),
            application_end=date.today() + timedelta(days=45),
            rule_pack_version_id=self.rule_version,
            target_levels=["DOUBLE_TEACHER_JUNIOR", "DOUBLE_TEACHER_INTERMEDIATE"],
            status="DRAFT",
        )
        self.recognition = HrDoubleTeacherRecognition.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            staff_master_id=self.staff,
            recognition_no="DT-HR09-2025-001",
            level="DOUBLE_TEACHER_JUNIOR",
            rule_pack_version_id=self.rule_version,
            effective_from=date.today() - timedelta(days=365),
            review_due_at=date.today() + timedelta(days=30),
            status="ACTIVE",
            recognition_authority="跃科大学双师型教师认定委员会",
        )
        self.risk = HrQualificationRiskCase.objects.create(
            tenant_id=self.company.pk,
            person_id=self.person,
            credential_id=self.credential.id,
            risk_type="CREDENTIAL_UNVERIFIED",
            severity="HIGH",
            owner="教师发展中心",
            due_at=date.today() + timedelta(days=7),
            status="OPEN",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR09-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

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
        page.on("response", lambda response: api_failures.append(f"{response.status} {response.url}") if "/api/v1/hr/qualifications" in response.url and response.status >= 400 else None)
        page.on("response", lambda response: static_failures.append(f"{response.status} {response.url}") if "/static/hr/" in response.url and response.status >= 400 else None)

    def test_capture_all_hr09_workspaces_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for mode, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
                    context = self.browser_context(browser, viewport)
                    page = context.new_page()
                    self.monitor(page, page_errors, console_errors, api_failures, static_failures)
                    for name, route in self.ROUTES:
                        response = page.goto(self.live_server_url + route, wait_until="networkidle")
                        self.assertIsNotNone(response, route)
                        self.assertEqual(response.status, 200, route)
                        self.assertEqual(page.locator(f'[data-module="HR09"][data-section="{name}"]').count(), 1, route)
                        self.assertEqual(page.locator(".hr09-nav a").count(), 6, route)
                        self.assertEqual(page.locator(".hr-v2-pagehead").count(), 1, route)
                        if name != "overview":
                            page.locator(".hr09-action-card").wait_for(state="visible", timeout=10000)
                        if mode == "mobile":
                            self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1, route)
                        page.screenshot(path=str(self.out_dir / f"{mode}-{name}.png"), full_page=True)
                    context.close()
            finally:
                browser.close()
        self.assertEqual(page_errors, [], "HR09 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR09 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR09 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR09 static failures: " + " | ".join(static_failures))

    def test_real_browser_closes_credential_batch_recheck_and_risk_actions(self):
        from playwright.sync_api import sync_playwright

        from hr_qualification.models import HrDoubleTeacherRecheckCase

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser, {"width": 1440, "height": 1000})
                page = context.new_page()
                self.monitor(page, page_errors, console_errors, api_failures, static_failures)

                def click_write_and_wait(button_name, response_suffix, expected_status):
                    """Wait for HR09's delayed reload as well as the write response."""
                    with page.expect_navigation(wait_until="networkidle") as navigation:
                        with page.expect_response(
                            lambda response: response.url.endswith(response_suffix)
                        ) as api_response:
                            page.get_by_role("button", name=button_name).click()
                    self.assertEqual(api_response.value.status, expected_status)
                    self.assertEqual(navigation.value.status, 200)

                page.goto(self.live_server_url + "/hr/qualifications/credentials/", wait_until="networkidle")
                click_write_and_wait("提交核验", "/submit-verification", 200)
                page.get_by_role("button", name="登记核验").click()
                click_write_and_wait("保存核验", "/verify", 200)

                page.goto(self.live_server_url + "/hr/double-teacher/", wait_until="networkidle")
                click_write_and_wait("发布批次", "/advance", 200)

                page.goto(self.live_server_url + "/hr/double-teacher/recognitions/", wait_until="networkidle")
                page.get_by_role("button", name="发起复核").click()
                click_write_and_wait("创建复核案例", "/recheck", 201)
                page.get_by_role("button", name="登记复核结论").click()
                click_write_and_wait("保存复核结论", "/decide", 200)

                page.goto(self.live_server_url + "/hr/qualifications/risks/", wait_until="networkidle")
                click_write_and_wait("确认接单", "/acknowledge", 200)
                page.get_by_role("button", name="解决风险").click()
                page.locator("[data-resolution]").fill("已完成证书原件核验并留存核验记录。")
                click_write_and_wait("确认已解决", "/resolve", 200)
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(self.out_dir / "desktop-real-actions-complete.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.credential.refresh_from_db()
        self.batch.refresh_from_db()
        self.recognition.refresh_from_db()
        self.risk.refresh_from_db()
        recheck = HrDoubleTeacherRecheckCase.objects.get(recognition_id=self.recognition)
        self.assertEqual(self.credential.status, "ACTIVE")
        self.assertEqual(self.batch.status, "PUBLISHED")
        self.assertEqual(self.recognition.status, "ACTIVE")
        self.assertEqual(recheck.status, "CLOSED")
        self.assertEqual(self.risk.status, "RESOLVED")
        self.assertEqual(page_errors, [], "HR09 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR09 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR09 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR09 static failures: " + " | ".join(static_failures))
