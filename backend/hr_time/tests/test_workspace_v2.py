"""HR11 V2 workspace, tenant boundary, and lifecycle contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from hr_time.api.workbench import (
    choices,
    create_close_period,
    close_action,
    exception_action,
    overtime_action,
    overtime_fact_action,
)
from hr_time.models import (
    HrAttendanceException,
    HrOvertimeRequest,
    HrOvertimeFact,
    HrTimeClosePeriod,
    HrTimeCloseSnapshot,
    HrWorkCalendar,
    HrWorkCalendarVersion,
)
from hr_time.views import _leave_workspace_rows


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"


class Hr11WorkspaceStaticContractTests(SimpleTestCase):
    def test_workspace_uses_shared_shell_and_all_seven_sections(self):
        template = (BACKEND_ROOT / "hr_time/templates/hr_time/workspace.html").read_text(encoding="utf-8")
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
        script = (FRONTEND_ROOT / "static/hr/js/pages/hr11-actions.js").read_text(encoding="utf-8")
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
            stylesheet = (FRONTEND_ROOT / f"static/hr/css/{name}").read_text(encoding="utf-8")
            self.assertNotIn("linear-gradient", stylesheet)
            self.assertNotIn("radial-gradient", stylesheet)
            self.assertIn("@media", stylesheet)

    def test_health_contract_does_not_report_completed_authority_as_pending(self):
        health = (BACKEND_ROOT / "hr_time/api/views.py").read_text(encoding="utf-8")
        self.assertNotIn('"status": "PENDING"', health)

    def test_leave_workspace_is_read_only_when_optional_schema_is_missing(self):
        class FailingRows:
            def __iter__(self):
                raise DatabaseError("missing calculation_snapshot")

        item = SimpleNamespace(
            id=19,
            staff_master_id=701,
            start_at="2026-09-01",
            end_at="2026-09-02",
            status="SUBMITTED",
            requested_amount="2.00",
            leave_type=SimpleNamespace(name="事假", requires_evidence=False),
            get_status_display=lambda: "已提交",
            get_unit_display=lambda: "天",
        )
        leaves = MagicMock()
        related = leaves.select_related.return_value
        related.prefetch_related.return_value.order_by.return_value.__getitem__.return_value = FailingRows()
        related.defer.return_value.order_by.return_value.__getitem__.return_value = [item]

        rows, warning, writes_available = _leave_workspace_rows(
            leaves,
            {701: "张老师 · T000701"},
        )

        self.assertFalse(writes_available)
        self.assertIn("数据库升级", warning)
        self.assertEqual(rows[0]["staff"], "张老师 · T000701")
        self.assertIsNone(rows[0]["evidence_count"])
        self.assertFalse(rows[0]["evidence_available"])
        self.assertFalse(rows[0]["writes_available"])
        related.defer.assert_called_once_with("calculation_snapshot")

        template = (BACKEND_ROOT / "hr_time/templates/hr_time/workspace.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("证明材料状态暂不可读取", template)
        self.assertIn("数据库升级期间不可办理", template)


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
            tenant_id=801, calendar=local_calendar, year=2026, version_no=1,
            status="PUBLISHED", published_at=timezone.now(), content_hash="a" * 64,
        )
        foreign_version = HrWorkCalendarVersion.objects.create(
            tenant_id=802, calendar=foreign_calendar, year=2026, version_no=1,
            status="PUBLISHED", published_at=timezone.now(), content_hash="b" * 64,
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

    def test_create_close_period_is_tenant_scoped_and_rejects_overlap(self):
        today = timezone.localdate()
        start = today.replace(day=1)
        response = self.call_for_tenant(
            801,
            create_close_period,
            self.request("/api/v1/hr/time/close-periods/create", {
                "startDate": start.isoformat(), "endDate": today.isoformat(),
            }),
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(HrTimeClosePeriod.objects.filter(tenant_id=801, start_date=start).exists())
        response = self.call_for_tenant(
            801,
            create_close_period,
            self.request("/api/v1/hr/time/close-periods/create", {
                "startDate": start.isoformat(), "endDate": today.isoformat(),
            }),
        )
        self.assertEqual(response.status_code, 409)

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

    def test_overtime_fact_verification_is_tenant_scoped_and_sealed(self):
        now = timezone.now()
        local = HrOvertimeFact.objects.create(
            tenant_id=801,
            staff_master_id=101,
            actual_start_at=now,
            actual_end_at=now + timedelta(hours=2),
            actual_minutes=120,
            eligible_minutes=90,
        )
        foreign = HrOvertimeFact.objects.create(
            tenant_id=802,
            staff_master_id=202,
            actual_start_at=now,
            actual_end_at=now + timedelta(hours=1),
            actual_minutes=60,
            eligible_minutes=60,
        )
        response = self.call_for_tenant(
            801,
            overtime_fact_action,
            self.request(
                f"/api/v1/hr/time/overtime-facts/{local.id}/verify",
                {
                    "settlementMode": "COMP_TIME",
                    "evidenceSource": "attendance-pair:801-101",
                    "idempotencyKey": "workspace-ot-verify-1",
                },
            ),
            local.id,
            "verify",
        )
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertEqual(local.verification_status, "VERIFIED")
        self.assertTrue(local.verify_receipt())

        response = self.call_for_tenant(
            801,
            overtime_fact_action,
            self.request(
                f"/api/v1/hr/time/overtime-facts/{foreign.id}/verify",
                {
                    "settlementMode": "COMP_TIME",
                    "evidenceSource": "foreign",
                    "idempotencyKey": "workspace-ot-verify-foreign",
                },
            ),
            foreign.id,
            "verify",
        )
        self.assertEqual(response.status_code, 404)

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
