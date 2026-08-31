"""Real Chromium acceptance for the HR11 attendance/time V2 workspace."""

from __future__ import annotations

import os
import base64
from datetime import date, time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr11VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster
        from hr_time.models import (
            HrAttendanceDayFact,
            HrAttendanceException,
            HrLeaveAccount,
            HrLeaveRequest,
            HrLeaveType,
            HrOvertimeRequest,
            HrShiftDefinition,
            HrShiftVersion,
            HrTimeClosePeriod,
            HrTimeRiskCase,
            HrWorkCalendar,
            HrWorkCalendarVersion,
        )
        from hr_time.services.leave_account_service import LeaveAccountService
        from hr_time.services.leave_request_service import LeaveRequestService

        self.company = Company.objects.create(
            company="跃科 HR11 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 11 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile(
                "hr11-visual.png",
                base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
                content_type="image/png",
            ),
        )
        self.user = get_user_model().objects.create_superuser(
            username="hr11-visual-auditor",
            email="hr11-visual@example.invalid",
            password="hr11-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR11",
            employee_last_name="视觉验收员",
            email="hr11-employee@example.invalid",
            phone="13800000011",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="林知时",
            status="ACTIVE",
        )
        HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="HR11-CLICK-001",
            legacy_employee_id=self.employee.pk,
            current_employment_status="ACTIVE",
        )
        today = timezone.localdate()
        self.calendar = HrWorkCalendar.objects.create(
            tenant_id=self.company.pk,
            code="HR11-SCHOOL-CAL",
            name="跃科学校行政日历",
        )
        self.calendar_version = HrWorkCalendarVersion.objects.create(
            tenant_id=self.company.pk,
            calendar=self.calendar,
            year=today.year,
            version_no=1,
            status="PUBLISHED",
            published_at=timezone.now(),
        )
        self.shift = HrShiftDefinition.objects.create(
            tenant_id=self.company.pk,
            code="HR11-DAY",
            name="行政白班",
        )
        self.shift_version = HrShiftVersion.objects.create(
            tenant_id=self.company.pk,
            shift=self.shift,
            version_no=1,
            start_time=time(8, 30),
            end_time=time(17, 30),
            effective_from=today.replace(day=1),
            published_at=timezone.now(),
        )
        HrAttendanceDayFact.objects.create(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            business_date=today,
            expected_minutes=480,
            actual_minutes=480,
            credited_minutes=480,
            status="PRESENT",
        )
        self.exception = HrAttendanceException.objects.create(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            business_date=today - timedelta(days=1),
            exception_code="MISSING_OUT",
            status="OPEN",
        )

        leave_type = HrLeaveType.objects.create(
            tenant_id=self.company.pk,
            code="HR11-ANNUAL",
            name="年休假",
            category="ANNUAL",
            unit="DAYS",
        )
        LeaveAccountService.grant(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            leave_type_id=leave_type.id,
            account_year=today.year,
            amount=5,
            effective_date=today,
        )
        account = HrLeaveAccount.objects.get(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            leave_type=leave_type,
            account_year=today.year,
        )
        self.leave = HrLeaveRequest.objects.create(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            leave_type=leave_type,
            start_at=today,
            end_at=today,
            requested_amount=1,
            unit="DAYS",
            account=account,
            status="DRAFT",
        )
        LeaveRequestService.submit(self.leave)

        now = timezone.now()
        self.overtime = HrOvertimeRequest.objects.create(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            requested_start_at=now + timedelta(days=1),
            requested_end_at=now + timedelta(days=1, hours=2),
            reason="开学数据核验",
            planned_minutes=120,
            status="SUBMITTED",
        )
        self.period = HrTimeClosePeriod.objects.create(
            tenant_id=self.company.pk,
            start_date=today.replace(day=1),
            end_date=today,
            status="OPEN",
        )
        self.risk = HrTimeRiskCase.objects.create(
            tenant_id=self.company.pk,
            risk_code="SCHEDULE_GAP",
            staff_master_id=self.employee.pk,
            severity="MEDIUM",
            summary="新学期排班尚未覆盖后续月份",
            status="OPEN",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR11-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.routes = (
            ("overview", "/hr/time/"),
            ("attendance", "/hr/time/attendance/"),
            ("schedule", "/hr/time/schedule/"),
            ("leave", "/hr/time/leave/"),
            ("overtime", "/hr/time/overtime/"),
            ("close", "/hr/time/close/"),
            ("risks", "/hr/time/risks/"),
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
        page.on("response", lambda response: api_failures.append(f"{response.status} {response.url}") if "/api/v1/hr/time" in response.url and response.status >= 400 else None)
        page.on("response", lambda response: static_failures.append(f"{response.status} {response.url}") if "/static/hr/" in response.url and response.status >= 400 else None)

    def test_capture_all_hr11_workspaces_desktop_and_mobile(self):
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
                        self.assertEqual(page.locator(f'[data-module="HR11"][data-section="{name}"]').count(), 1, route)
                        self.assertEqual(page.locator(".hr11-nav a").count(), 7, route)
                        self.assertEqual(page.locator(".hr-v2-pagehead").count(), 1, route)
                        if mode == "mobile":
                            self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1, route)
                        page.screenshot(path=str(self.out_dir / f"{mode}-{name}.png"), full_page=True)
                    context.close()
            finally:
                browser.close()
        self.assertEqual(page_errors, [], "HR11 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR11 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR11 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR11 static failures: " + " | ".join(static_failures))

    def test_real_browser_completes_time_fact_chain(self):
        from playwright.sync_api import sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self.browser_context(browser, {"width": 1440, "height": 1000})
                page = context.new_page()
                self.monitor(page, page_errors, console_errors, api_failures, static_failures)

                page.goto(self.live_server_url + "/hr/time/schedule/", wait_until="networkidle")
                page.get_by_role("button", name="新建生效排班").click()
                page.get_by_label("人员").select_option(str(self.employee.pk))
                page.get_by_label("工作日历版本").select_option(str(self.calendar_version.pk))
                page.get_by_label("班次版本").select_option(str(self.shift_version.pk))
                page.get_by_label("生效日期").fill((timezone.localdate() + timedelta(days=1)).isoformat())
                with page.expect_response(lambda response: response.url.endswith("/schedules/create")) as scheduled:
                    page.get_by_role("button", name="确认办理").click()
                self.assertEqual(scheduled.value.status, 201)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/time/attendance/", wait_until="networkidle")
                page.get_by_role("button", name="解决异常").click()
                page.get_by_label("处理说明").fill("已核对设备离线记录与教师签退证明")
                with page.expect_response(lambda response: response.url.endswith("/resolve")) as resolved:
                    page.get_by_role("button", name="确认办理").click()
                self.assertEqual(resolved.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/time/leave/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/approve")) as leave_approved:
                    page.get_by_role("button", name="批准", exact=True).click()
                self.assertEqual(leave_approved.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/time/overtime/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/approve")) as overtime_approved:
                    page.get_by_role("button", name="批准申请").click()
                self.assertEqual(overtime_approved.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/time/risks/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/acknowledge")) as acknowledged:
                    page.get_by_role("button", name="确认接单").click()
                self.assertEqual(acknowledged.value.status, 200)
                page.wait_for_load_state("networkidle")

                page.goto(self.live_server_url + "/hr/time/close/", wait_until="networkidle")
                with page.expect_response(lambda response: response.url.endswith("/precheck")) as prechecked:
                    page.get_by_role("button", name="关账预检").click()
                self.assertEqual(prechecked.value.status, 200)
                self.assertIn("预检通过", page.locator("[data-feedback]").text_content())
                with page.expect_response(lambda response: response.url.endswith("/close")) as closed:
                    page.get_by_role("button", name="正式关闭").click()
                self.assertEqual(closed.value.status, 200)
                page.locator("[data-status]", has_text="已关闭").wait_for(timeout=10000)
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(self.out_dir / "desktop-real-time-chain-complete.png"), full_page=True)
                context.close()
            finally:
                browser.close()
        self.assertEqual(page_errors, [], "HR11 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR11 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR11 API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR11 static failures: " + " | ".join(static_failures))
