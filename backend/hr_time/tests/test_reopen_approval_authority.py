"""P0 authority contracts for reopening an immutable HR11 close period."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from horilla.hr_event_registry import global_event_registry
from hr_staff.models import HrOutboxEvent
from hr_time.constants import ALL_TIME_PERMISSIONS
from hr_time.models import HrAttendanceDayFact, HrTimeClosePeriod, HrTimeCorrectionBatch
from hr_time.services.close_service import CloseService, CloseServiceError


class ReopenApprovalAuthorityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(username="p0-reopen-requester")
        self.approver = User.objects.create_user(username="p0-reopen-approver")
        self.other = User.objects.create_user(username="p0-reopen-other")
        self.period = HrTimeClosePeriod.objects.create(
            tenant_id=1101,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        self.fact = HrAttendanceDayFact.objects.create(
            tenant_id=1101,
            staff_master_id=7001,
            business_date=date(2026, 8, 3),
            status="PRESENT",
            expected_minutes=480,
            actual_minutes=480,
            credited_minutes=480,
        )
        CloseService.close(tenant_id=1101, period=self.period)
        self.period.refresh_from_db()

    def request_reopen(self, key="p0-reopen-key"):
        return CloseService.request_reopen(
            tenant_id=1101,
            period=self.period,
            reason="补录经核验的请假事实",
            actor_user=self.requester,
            idempotency_key=key,
        )

    def test_request_keeps_period_and_facts_frozen_until_independent_approval(self):
        batch = self.request_reopen()
        self.period.refresh_from_db()
        self.fact.refresh_from_db()

        self.assertEqual(self.period.status, "CLOSED")
        self.assertTrue(self.fact.finalized)
        self.assertEqual(batch.status, HrTimeCorrectionBatch.Status.REQUESTED)
        self.assertIsNone(batch.approved_by_id)
        self.assertTrue(
            HrOutboxEvent.objects.filter(
                tenant_id=1101,
                event_type="hr.time.time_close.reopen_requested",
                correlation_id="p0-reopen-key",
            ).exists()
        )

        with self.assertRaises(CloseServiceError) as same_actor:
            CloseService.approve_reopen(
                tenant_id=1101,
                period=self.period,
                batch=batch,
                actor_user=self.requester,
            )
        self.assertEqual(same_actor.exception.code, "SEPARATION_OF_DUTY_VIOLATION")
        self.fact.refresh_from_db()
        self.assertTrue(self.fact.finalized)

        approved = CloseService.approve_reopen(
            tenant_id=1101,
            period=self.period,
            batch=batch,
            actor_user=self.approver,
        )
        self.period.refresh_from_db()
        self.fact.refresh_from_db()
        self.assertEqual(self.period.status, "REOPENED")
        self.assertFalse(self.fact.finalized)
        self.assertEqual(approved.status, HrTimeCorrectionBatch.Status.APPROVED)
        self.assertEqual(approved.approved_by_id, self.approver.id)
        self.assertEqual(
            set(
                HrOutboxEvent.objects.filter(
                    tenant_id=1101,
                    correlation_id="p0-reopen-key",
                ).values_list("event_type", flat=True)
            ),
            {
                "hr.time.time_close.reopen_requested",
                "hr.time.time_close.reopen_approved",
                "hr.time.time_close.reopened",
            },
        )

    def test_request_is_idempotent_and_conflicting_reuse_fails_closed(self):
        first = self.request_reopen("same-key")
        replay = self.request_reopen("same-key")
        self.assertEqual(first.id, replay.id)
        self.assertEqual(
            HrTimeCorrectionBatch.objects.filter(tenant_id=1101).count(), 1
        )

        with self.assertRaises(CloseServiceError) as conflict:
            CloseService.request_reopen(
                tenant_id=1101,
                period=self.period,
                reason="不同申请内容",
                actor_user=self.requester,
                idempotency_key="same-key",
            )
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_cross_tenant_approval_fails_without_unfreezing(self):
        batch = self.request_reopen()
        with self.assertRaises(CloseServiceError) as denied:
            CloseService.approve_reopen(
                tenant_id=2202,
                period=self.period,
                batch=batch,
                actor_user=self.approver,
            )
        self.assertEqual(denied.exception.code, "CROSS_TENANT_REFERENCE")
        self.fact.refresh_from_db()
        self.assertTrue(self.fact.finalized)

    def test_permission_and_event_contracts_are_registered(self):
        permission_keys = {key for key, _description in ALL_TIME_PERMISSIONS}
        self.assertIn("hr.time.close.reopen_request", permission_keys)
        self.assertIn("hr.time.close.reopen_approve", permission_keys)
        global_event_registry.get("hr.time.time_close.reopen_requested")
        global_event_registry.get("hr.time.time_close.reopen_approved")
