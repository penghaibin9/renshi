"""HR11 V2 workspace, tenant boundary, and lifecycle contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from hr_time.api.workbench import (
    choices,
    close_action,
    exception_action,
    overtime_action,
)
from hr_time.models import (
    HrAttendanceException,
    HrOvertimeRequest,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
    HrWorkCalendar,
    HrWorkCalendarVersion,
)


ROOT = Path(__file__).resolve().parents[2]


class Hr11WorkspaceStaticContractTests(SimpleTestCase):
    def test_workspace_uses_shared_shell_and_all_seven_sections(self):
        template = (ROOT / "hr_time/templates/hr_time/workspace.html").read_text(encoding="utf-8")
        self.assertIn('{% extends "index.html" %}', template)
        self.assertIn('class="hr-v2-page hr11"', template)
        self.assertIn('data-module="HR11"', template)
        for route_name in (
            "hr11-overview",
            "hr11-attendance",
            "hr11-schedule",
            "hr11-leave",
            "hr11-overtime",
            "hr11-close",
            "hr11-risks",
        ):
            self.assertIn(route_name, template)
        self.assertNotIn("<!DOCTYPE", template)
        self.assertNotIn('href="#"', template)

    def test_action_layer_uses_business_choices_and_no_fake_client_state(self):
        script = (ROOT / "static/hr/js/pages/hr11-actions.js").read_text(encoding="utf-8")
        self.assertIn("/workbench/choices", script)
        self.assertIn("/schedules/create", script)
        for forbidden in (
            "Staff ID",
            "人员 ID",
            "Calendar Version ID",
            "Shift Version ID",
            "Math.random",
            "localStorage",
            "sessionStorage",
            "prompt(",
            'href="#"',
        ):
            self.assertNotIn(forbidden, script)

    def test_visual_layer_is_flat_and_responsive(self):
        for name in ("hr11-actions.css", "hr11-workspace.css"):
            stylesheet = (ROOT / f"static/hr/css/{name}").read_text(encoding="utf-8")
            self.assertNotIn("linear-gradient", stylesheet)
            self.assertNotIn("radial-gradient", stylesheet)
            self.assertIn("@media", stylesheet)

    def test_health_contract_does_not_report_completed_authority_as_pending(self):
        health = (ROOT / "hr_time/api/views.py").read_text(encoding="utf-8")
        self.assertNotIn('"status": "PENDING"', health)


class Hr11WorkbenchTenantAndLifecycleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="hr11-workbench-test",
            email="hr11-workbench@example.invalid",
            password="test-only-password",
        )
        self.reopen_approver = get_user_model().objects.create_superuser(
            username="hr11-reopen-approver",
            email="hr11-reopen-approver@example.invalid",
            password="test-only-password",
        )

    def request(self, path, body=None):
        if body is None:
            request = self.factory.get(path)
        else:
            request = self.factory.post(path, data=json.dumps(body), content_type="application/json")
        request.user = self.user
        return request

    def call_for_tenant(self, tenant_id, callback, *args):
        with patch("hr_time.api.views.resolve_tenant_from_request", return_value=tenant_id):
            return callback(*args)

    def test_choices_never_include_another_school_calendar(self):
        local_calendar = HrWorkCalendar.objects.create(
            tenant_id=801, code="LOCAL-CAL", name="本校行政日历"
        )
        foreign_calendar = HrWorkCalendar.objects.create(
            tenant_id=802, code="FOREIGN-CAL", name="其他学校日历"
        )
        local_version = HrWorkCalendarVersion.objects.create(
            tenant_id=801, calendar=local_calendar, year=2026, version_no=1, status="PUBLISHED"
        )
        foreign_version = HrWorkCalendarVersion.objects.create(
            tenant_id=802, calendar=foreign_calendar, year=2026, version_no=1, status="PUBLISHED"
        )
        response = self.call_for_tenant(
            801,
            choices,
            self.request("/api/v1/hr/time/workbench/choices"),
        )
        values = {
            item["value"]
            for item in json.loads(response.content)["data"]["calendarVersions"]
        }
        self.assertIn(local_version.id, values)
        self.assertNotIn(foreign_version.id, values)

    def test_exception_action_is_tenant_scoped_and_stateful(self):
        local = HrAttendanceException.objects.create(
            tenant_id=801,
            staff_master_id=101,
            business_date=timezone.localdate(),
            exception_code="MISSING_IN",
        )
        foreign = HrAttendanceException.objects.create(
            tenant_id=802,
            staff_master_id=202,
            business_date=timezone.localdate(),
            exception_code="MISSING_OUT",
        )
        response = self.call_for_tenant(
            801,
            exception_action,
            self.request(f"/api/v1/hr/time/exceptions/{local.id}/review", {}),
            local.id,
            "review",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "REVIEWING")

        response = self.call_for_tenant(
            801,
            exception_action,
            self.request(f"/api/v1/hr/time/exceptions/{foreign.id}/review", {}),
            foreign.id,
            "review",
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, "OPEN")

    def test_overtime_approval_changes_only_current_school_request(self):
        now = timezone.now()
        local = HrOvertimeRequest.objects.create(
            tenant_id=801,
            staff_master_id=101,
            requested_start_at=now,
            requested_end_at=now + timedelta(hours=2),
            reason="开学准备",
            planned_minutes=120,
            status="SUBMITTED",
        )
        foreign = HrOvertimeRequest.objects.create(
            tenant_id=802,
            staff_master_id=202,
            requested_start_at=now,
            requested_end_at=now + timedelta(hours=1),
            reason="其他学校事项",
            planned_minutes=60,
            status="SUBMITTED",
        )
        response = self.call_for_tenant(
            801,
            overtime_action,
            self.request(f"/api/v1/hr/time/overtime/{local.id}/approve", {}),
            local.id,
            "approve",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(local.status, "APPROVED")
        self.assertEqual(foreign.status, "SUBMITTED")

    def test_close_action_creates_real_snapshot_and_rejects_foreign_period(self):
        today = timezone.localdate()
        local = HrTimeClosePeriod.objects.create(
            tenant_id=801,
            start_date=today.replace(day=1),
            end_date=today,
        )
        foreign = HrTimeClosePeriod.objects.create(
            tenant_id=802,
            start_date=today.replace(day=1),
            end_date=today,
        )
        response = self.call_for_tenant(
            801,
            close_action,
            self.request(f"/api/v1/hr/time/close-periods/{local.id}/close", {}),
            local.id,
            "close",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "CLOSED")
        self.assertTrue(HrTimeCloseSnapshot.objects.filter(tenant_id=801, period=local).exists())

        response = self.call_for_tenant(
            801,
            close_action,
            self.request(
                f"/api/v1/hr/time/close-periods/{local.id}/reopen",
                {
                    "reason": "更正已核验考勤事实",
                    "idempotencyKey": "workspace-reopen-1",
                },
            ),
            local.id,
            "reopen",
        )
        self.assertEqual(response.status_code, 201)
        local.refresh_from_db()
        self.assertEqual(local.status, "CLOSED")
        batch = local.correction_batches.get(request_key="workspace-reopen-1")
        approve_request = self.request(
            f"/api/v1/hr/time/close-periods/{local.id}/approve-reopen",
            {"correctionBatchId": batch.id},
        )
        approve_request.user = self.reopen_approver
        response = self.call_for_tenant(
            801,
            close_action,
            approve_request,
            local.id,
            "approve-reopen",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "REOPENED")

        response = self.call_for_tenant(
            801,
            close_action,
            self.request(f"/api/v1/hr/time/close-periods/{local.id}/close", {}),
            local.id,
            "close",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.status, "CLOSED")
        self.assertEqual(HrTimeCloseSnapshot.objects.filter(tenant_id=801, period=local).count(), 2)
        self.assertIsNotNone(local.correction_batches.latest("id").after_snapshot_id)

        response = self.call_for_tenant(
            801,
            close_action,
            self.request(f"/api/v1/hr/time/close-periods/{foreign.id}/close", {}),
            foreign.id,
            "close",
        )
        self.assertEqual(response.status_code, 404)
