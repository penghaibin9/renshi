"""Real Chromium acceptance for the HR11 attendance/time V2 workspace."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, time, timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone


def _write_and_wait_for_reload(page, button, api_url, expected_status, *, timeout=15000):
    """Wait for the production POST and its delayed same-page document reload.

    The old document may already be network-idle when its 250ms reload timer
    is pending. A load-state sample does not await that future navigation.
    Arm all observers before the one real click; history events, iframe loads,
    XHR GETs and a different page cannot satisfy this document checkpoint.
    No sleep, manual reload, intercepted transport or repeated business write.
    """
    document_url = page.url
    with page.expect_event("load", timeout=timeout):
        with page.expect_response(
            lambda response: response.url == document_url
            and response.request.method == "GET"
            and response.request.is_navigation_request()
            and response.request.frame == page.main_frame,
            timeout=timeout,
        ) as document:
            with page.expect_response(
                lambda response: response.url == api_url
                and response.request.method == "POST",
                timeout=timeout,
            ) as written:
                button.click()
            assert written.value.status == expected_status, (
                f"Business write returned HTTP {written.value.status}, expected {expected_status}"
            )
    assert document.value.status == 200, f"Reload returned HTTP {document.value.status}"
    document.value.finished()
    assert page.url == document_url, "Business action left its original work area"
    # Response bodies can be discarded on navigation; authoritative facts are
    # read from MySQL after the browser loop, not from a retried POST.
    return {"writeStatus": written.value.status, "documentStatus": document.value.status}


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr11VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster
        from hr_time.enums import CalendarDayType, PolicyStatus
        from hr_time.models import (
            HrAttendanceDayFact,
            HrAttendanceException,
            HrCalendarDay,
            HrLeaveAccount,
            HrLeavePolicyPack,
            HrLeavePolicyVersion,
            HrLeaveRequest,
            HrLeaveType,
            HrOvertimeRequest,
            HrScheduleAssignment,
            HrShiftDefinition,
            HrShiftVersion,
            HrTimeClosePeriod,
            HrTimeRiskCase,
            HrWorkCalendar,
            HrWorkCalendarVersion,
        )
        from hr_time.services.calendar_service import CalendarService
        from hr_time.services.leave_account_service import LeaveAccountService
        from hr_time.services.leave_request_service import LeaveRequestService
        from hr_time.services.schedule_service import ScheduleService

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
            source_type="VISUAL_TEST",
            source_ref="HR11 visual authority seed",
            status="DRAFT",
        )
        for calendar_day in (today, today + timedelta(days=1)):
            HrCalendarDay.objects.create(
                tenant_id=self.company.pk,
                calendar_version=self.calendar_version,
                date=calendar_day,
                day_type=CalendarDayType.REGULAR_WORKDAY,
                is_working_day=True,
                expected_work_minutes=480,
            )
        self.calendar_version = CalendarService.publish_version(
            self.calendar_version,
            actor_user=self.user,
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
        ScheduleService.create_assignment(
            HrScheduleAssignment(
                tenant_id=self.company.pk,
                staff_master_id=self.employee.pk,
                calendar_version=self.calendar_version,
                shift_version=self.shift_version,
                effective_from=today.replace(day=1),
                effective_to=today + timedelta(days=1),
                source="HR11_VISUAL_BASELINE",
            )
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
            paid_classification="PAID",
        )
        leave_policy_pack = HrLeavePolicyPack.objects.create(
            tenant_id=self.company.pk,
            code="HR11-ANNUAL-POLICY",
            name="年休假政策",
            jurisdiction="CN-HN",
            worker_scope="ALL_ACTIVE_STAFF",
        )
        leave_policy_version = HrLeavePolicyVersion.objects.create(
            tenant_id=self.company.pk,
            leave_policy_pack=leave_policy_pack,
            leave_type=leave_type,
            version_no=1,
            status=PolicyStatus.PUBLISHED,
            entitlement_mode="GRANT",
            eligibility_rule={"scope": "MANUAL_ENROLLMENT"},
            grant_accrual_rule={"annualGrant": "5", "unit": leave_type.unit},
            effective_from=date(today.year, 1, 1),
            published_by=self.user,
        )
        leave_policy_pack.current_version_id = leave_policy_version.id
        leave_policy_pack.save(update_fields=["current_version_id", "updated_at"])
        LeaveAccountService.grant(
            tenant_id=self.company.pk,
            staff_master_id=self.employee.pk,
            leave_type_id=leave_type.id,
            account_year=today.year,
            amount=5,
            effective_date=today,
            policy_version_id=leave_policy_version.id,
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
            policy_version_id=leave_policy_version.id,
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
        from playwright.sync_api import expect, sync_playwright

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
                        # Six grouped workspaces; all seven canonical/compatibility
                        # routes above must still render their own business section.
                        expect(page.locator(".hr11-nav a")).to_have_text([
                            "01制度与规则", "02校历与排班", "03打卡与工时",
                            "04异常补卡与加班", "05请假休假", "06月结台账",
                        ])
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
        from playwright.sync_api import expect, sync_playwright

        page_errors, console_errors, api_failures, static_failures = [], [], [], []
        writes, checkpoints, facts = [], [], {}
        result = "FAIL"
        api_root = self.live_server_url + "/api/v1/hr/time"
        expected_writes = [
            "/schedules/create",
            f"/exceptions/{self.exception.pk}/resolve",
            f"/leaves/{self.leave.pk}/approve",
            f"/overtime/{self.overtime.pk}/approve",
            f"/risks/{self.risk.pk}/acknowledge",
            f"/close-periods/{self.period.pk}/precheck",
            f"/close-periods/{self.period.pk}/close",
        ]
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = self.browser_context(browser, {"width": 1440, "height": 1000})
                    page = context.new_page()
                    self.monitor(page, page_errors, console_errors, api_failures, static_failures)
                    page.on("request", lambda request: writes.append(request.url[len(api_root):])
                            if request.method == "POST" and request.url.startswith(api_root + "/") else None)

                    def write(button, suffix, status=200):
                        checkpoint = _write_and_wait_for_reload(page, button, api_root + suffix, status)
                        checkpoints.append({"path": suffix, **checkpoint})
                        expect(page.locator("[data-module='HR11']")).to_be_visible()

                    def row(record_id):
                        target = page.locator(f".hr11-row[data-record-id='{record_id}']")
                        expect(target).to_have_count(1)
                        return target

                    page.goto(self.live_server_url + "/hr/time/schedule/", wait_until="networkidle")
                    page.get_by_role("button", name="新建生效排班").click()
                    dialog = page.locator(".hr11 [data-dialog]")
                    expect(dialog).to_be_visible(timeout=10000)
                    expect(dialog.locator(".hr11-field > span")).to_have_text([
                        "人员", "工作日历版本", "班次版本", "生效日期", "失效日期",
                    ])
                    dialog.locator("select[name='staffId']").select_option(str(self.employee.pk))
                    dialog.locator("select[name='calendarVersionId']").select_option(str(self.calendar_version.pk))
                    dialog.locator("select[name='shiftVersionId']").select_option(str(self.shift_version.pk))
                    dialog.locator("input[name='effectiveFrom']").fill((timezone.localdate() + timedelta(days=1)).isoformat())
                    write(dialog.get_by_role("button", name="确认办理", exact=True), expected_writes[0], 201)
                    expect(page.locator(".hr11-row").filter(has_text="HR11_WORKBENCH")).to_have_count(1)

                    page.goto(self.live_server_url + "/hr/time/attendance/", wait_until="networkidle")
                    row(self.exception.pk).get_by_role("button", name="解决异常").click()
                    expect(dialog).to_be_visible(timeout=10000)
                    dialog.get_by_label("处理说明").fill("已核对设备离线记录与教师签退证明")
                    write(dialog.get_by_role("button", name="确认办理", exact=True), expected_writes[1])
                    expect(row(self.exception.pk).locator("[data-action]")).to_have_count(0)
                    expect(row(self.exception.pk)).to_contain_text("已核对设备离线记录与教师签退证明")

                    page.goto(self.live_server_url + "/hr/time/leave/", wait_until="networkidle")
                    write(row(self.leave.pk).get_by_role("button", name="批准", exact=True), expected_writes[2])
                    expect(row(self.leave.pk).get_by_role("button", name="办理销假", exact=True)).to_be_visible()
                    expect(row(self.leave.pk).locator("[data-action='leave-approve']")).to_have_count(0)

                    page.goto(self.live_server_url + "/hr/time/overtime/", wait_until="networkidle")
                    write(row(self.overtime.pk).get_by_role("button", name="批准申请", exact=True), expected_writes[3])
                    expect(row(self.overtime.pk).locator("[data-action]")).to_have_count(0)

                    page.goto(self.live_server_url + "/hr/time/risks/", wait_until="networkidle")
                    write(row(self.risk.pk).get_by_role("button", name="确认接单", exact=True), expected_writes[4])
                    expect(row(self.risk.pk).locator("[data-action='risk-acknowledge']")).to_have_count(0)
                    expect(row(self.risk.pk).get_by_role("button", name="解决风险", exact=True)).to_be_visible()

                    page.goto(self.live_server_url + "/hr/time/close/", wait_until="networkidle")
                    # Precheck intentionally does not reload or create a close fact.
                    with page.expect_response(
                        lambda response: response.url == api_root + expected_writes[5]
                        and response.request.method == "POST"
                    ) as prechecked:
                        row(self.period.pk).get_by_role("button", name="关账预检", exact=True).click()
                    self.assertEqual(prechecked.value.status, 200)
                    precheck = prechecked.value.json()["data"]
                    self.assertTrue(precheck["ready"])
                    self.assertEqual(precheck["blockers"], [])
                    expect(page.locator("[data-feedback]")).to_contain_text("预检通过")
                    checkpoints.append({"path": expected_writes[5], "writeStatus": 200, "ready": True, "blockers": []})
                    write(row(self.period.pk).get_by_role("button", name="正式关闭", exact=True), expected_writes[6])
                    expect(row(self.period.pk).locator("[data-status]")).to_have_text("已关闭")
                    expect(row(self.period.pk).get_by_role("button", name="申请重开", exact=True)).to_be_visible()
                    page.screenshot(path=str(self.out_dir / "desktop-real-time-chain-complete.png"), full_page=True)
                    context.close()
                except Exception:
                    if "page" in locals() and not page.is_closed():
                        try:
                            page.screenshot(path=str(self.out_dir / "desktop-real-time-chain-failed.png"), full_page=True)
                        except Exception:
                            pass  # Preserve the original assertion/navigation error.
                    raise
                finally:
                    browser.close()

            # Independent authoritative readbacks only after Playwright's loop
            # stops. No async-safety bypass and no prefilled final business facts.
            from hr_time.models import (
                HrAbsenceFact, HrLeaveLedgerEntry, HrPayrollTimeBasis,
                HrScheduleAssignment, HrTimeCloseSnapshot,
            )

            self.exception.refresh_from_db()
            self.leave.refresh_from_db()
            self.overtime.refresh_from_db()
            self.risk.refresh_from_db()
            self.period.refresh_from_db()
            self.assertEqual(self.exception.status, "RESOLVED")
            self.assertEqual(self.leave.status, "APPROVED")
            self.assertEqual(self.overtime.status, "APPROVED")
            self.assertEqual(self.risk.status, "ACKNOWLEDGED")
            self.assertEqual(self.period.status, "CLOSED")
            self.assertEqual(self.period.closed_by_id, self.user.pk)
            self.assertIsNotNone(self.period.closed_at)
            self.assertEqual(HrScheduleAssignment.objects.filter(
                tenant_id=self.company.pk, staff_master_id=self.employee.pk,
                source="HR11_WORKBENCH",
            ).count(), 1)
            absences = HrAbsenceFact.objects.filter(
                tenant_id=self.company.pk, leave_request=self.leave,
            )
            self.assertEqual(absences.count(), 1)
            absence = absences.get()
            self.assertEqual(absence.status, "ACTIVE")
            self.assertEqual(absence.paid_classification, "PAID")
            self.assertEqual(absence.policy_version_id, self.leave.policy_version_id)
            self.assertEqual(absence.scheduled_minutes_impacted, 480)
            ledger = HrLeaveLedgerEntry.objects.filter(
                tenant_id=self.company.pk, account_id=self.leave.account_id,
            )
            self.assertEqual(ledger.filter(entry_type="USE").count(), 1)
            self.assertEqual(ledger.filter(entry_type="RESERVATION_RELEASE").count(), 1)
            self.assertEqual(HrTimeCloseSnapshot.objects.filter(
                tenant_id=self.company.pk, period=self.period,
            ).count(), 1)
            snapshot = HrTimeCloseSnapshot.objects.get(
                pk=self.period.snapshot_id, tenant_id=self.company.pk, period=self.period,
            )
            self.assertEqual(len(snapshot.leave_ledger_hash), 64)
            self.assertEqual(HrPayrollTimeBasis.objects.filter(
                tenant_id=self.company.pk, close_snapshot=snapshot,
                staff_master_id=self.employee.pk,
            ).count(), 1)
            self.assertEqual(writes, expected_writes, "Every business POST must occur exactly once, in order")
            self.assertEqual(len(checkpoints), 7)
            self.assertEqual(page_errors, [], "HR11 page errors: " + " | ".join(page_errors))
            self.assertEqual(console_errors, [], "HR11 console errors: " + " | ".join(console_errors))
            self.assertEqual(api_failures, [], "HR11 API failures: " + " | ".join(api_failures))
            self.assertEqual(static_failures, [], "HR11 static failures: " + " | ".join(static_failures))
            facts = {"exception": self.exception.status, "leave": self.leave.status,
                     "overtimeRequest": self.overtime.status, "risk": self.risk.status,
                     "period": self.period.status, "absenceCount": 1, "usageCount": 1,
                     "reservationReleaseCount": 1, "closeSnapshotCount": 1,
                     "payrollTimeBasisCount": 1, "paidClassification": absence.paid_classification}
            result = "PASS"
        finally:
            (self.out_dir / "real-time-chain-seal.json").write_text(json.dumps({
                "productSha": os.getenv("HR_PRODUCT_SHA", "UNSPECIFIED"),
                "checkoutSha": os.getenv("GITHUB_SHA", "LOCAL"),
                "result": result, "scope": "existing HR11 technical-admin case; synthetic prerequisites; real service writes",
                "postPaths": writes, "checkpoints": checkpoints, "facts": facts,
                "pageErrors": page_errors, "consoleErrors": console_errors,
                "apiFailures": api_failures, "staticFailures": static_failures,
                "httpReplacements": False, "manualReloads": 0, "writeRetries": 0,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
