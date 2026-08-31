"""Reliable HR05 outbox dispatch: claim lease, fail-closed and explicit ACK."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_onboarding.jobs.outbox_dispatcher import (
    BASE_RETRY_SECONDS,
    MAX_ATTEMPTS,
    DispatchResult,
    OutboxHandlerRegistry,
    _claim_batch,
    dispatch_pending,
)
from hr_onboarding.models import HrOnboardingOutboxEvent
from hr_onboarding.services.outbox_service import enqueue_outbox, mark_sent


class _Handler:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def deliver(self, envelope):
        self.calls.append(envelope)
        if self.error is not None:
            raise self.error
        return self.result


class ReliableOutboxDispatcherTests(TestCase):
    now = timezone.now().replace(microsecond=0)

    def _event(self, event_type="StaffActivated", tenant_id=1):
        return enqueue_outbox(
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_type="HrOnboardingCase",
            aggregate_id="case-1",
            correlation_id="corr-1",
            payload={"case_id": "case-1"},
        )

    def _registry(self, event_type, handler):
        registry = OutboxHandlerRegistry()
        registry.register(event_type, handler)
        return registry

    def test_unknown_event_fails_closed_and_schedules_retry(self):
        event = self._event("UnknownEvent")

        result = dispatch_pending(
            tenant_id=1,
            registry=OutboxHandlerRegistry(),
            worker_id="worker-a",
            now=self.now,
        )

        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.PENDING)
        self.assertEqual(event.attempts, 1)
        self.assertEqual(
            event.next_attempt_at,
            self.now + timedelta(seconds=BASE_RETRY_SECONDS),
        )
        self.assertIn("HANDLER_NOT_REGISTERED", event.last_error)
        self.assertEqual(event.lease_owner, "")
        self.assertIsNone(event.lease_expires_at)
        self.assertEqual(result["retrying"], 1)
        self.assertEqual(result["dispatched"], 0)

        deferred = dispatch_pending(
            tenant_id=1,
            registry=OutboxHandlerRegistry(),
            worker_id="worker-b",
            now=self.now + timedelta(seconds=BASE_RETRY_SECONDS - 1),
        )
        self.assertEqual(deferred["total"], 0)

    def test_only_explicit_ack_with_external_ref_marks_sent(self):
        event = self._event()
        handler = _Handler(DispatchResult.ack("iam-receipt-1"))

        result = dispatch_pending(
            tenant_id=1,
            registry=self._registry("StaffActivated", handler),
            worker_id="worker-a",
            now=self.now,
        )

        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.SENT)
        self.assertEqual(event.external_ref, "iam-receipt-1")
        self.assertEqual(event.attempts, 1)
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual(handler.calls[0].event_id, event.event_id)
        self.assertEqual(handler.calls[0].tenant_id, 1)
        self.assertEqual(result["dispatched"], 1)

    def test_truthy_non_contract_result_never_marks_sent(self):
        event = self._event()
        handler = _Handler(True)

        with self.assertLogs(
            "hr_onboarding.jobs.outbox_dispatcher", level="ERROR"
        ):
            dispatch_pending(
                tenant_id=1,
                registry=self._registry("StaffActivated", handler),
                worker_id="worker-a",
                now=self.now,
            )

        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.PENDING)
        self.assertEqual(event.attempts, 1)
        self.assertIn("INVALID_HANDLER_RESULT", event.last_error)

    def test_compatibility_mark_sent_also_requires_external_receipt(self):
        event = self._event()

        with self.assertRaisesRegex(ValueError, "ACK_RECEIPT_REQUIRED"):
            mark_sent(event.event_id, external_ref="")

        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.PENDING)

    def test_failure_uses_exponential_backoff_then_terminal_failed(self):
        event = self._event()
        event.attempts = MAX_ATTEMPTS - 1
        event.save(update_fields=["attempts"])
        handler = _Handler(error=TimeoutError("IAM timeout"))

        with self.assertLogs(
            "hr_onboarding.jobs.outbox_dispatcher", level="ERROR"
        ):
            result = dispatch_pending(
                tenant_id=1,
                registry=self._registry("StaffActivated", handler),
                worker_id="worker-a",
                now=self.now,
            )

        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.FAILED)
        self.assertEqual(event.attempts, MAX_ATTEMPTS)
        self.assertIsNone(event.next_attempt_at)
        self.assertIn("IAM timeout", event.last_error)
        self.assertEqual(result["failed"], 1)

    def test_second_failed_attempt_doubles_retry_delay(self):
        event = self._event()
        event.attempts = 1
        event.save(update_fields=["attempts"])
        handler = _Handler(DispatchResult.retry("downstream busy"))

        result = dispatch_pending(
            tenant_id=1,
            registry=self._registry("StaffActivated", handler),
            worker_id="worker-a",
            now=self.now,
        )

        event.refresh_from_db()
        self.assertEqual(event.attempts, 2)
        self.assertEqual(
            event.next_attempt_at,
            self.now + timedelta(seconds=BASE_RETRY_SECONDS * 2),
        )
        self.assertEqual(event.last_error, "downstream busy")
        self.assertEqual(result["retrying"], 1)

    def test_active_lease_excludes_other_worker_and_expired_lease_is_reclaimed(self):
        event = self._event()
        event.lease_owner = "dead-worker"
        event.lease_expires_at = self.now + timedelta(minutes=1)
        event.save(update_fields=["lease_owner", "lease_expires_at"])
        handler = _Handler(DispatchResult.ack("receipt-after-reclaim"))
        registry = self._registry("StaffActivated", handler)

        blocked = dispatch_pending(
            tenant_id=1,
            registry=registry,
            worker_id="worker-b",
            now=self.now,
        )
        self.assertEqual(blocked["total"], 0)
        self.assertEqual(len(handler.calls), 0)

        event.lease_expires_at = self.now - timedelta(seconds=1)
        event.save(update_fields=["lease_expires_at"])
        reclaimed = dispatch_pending(
            tenant_id=1,
            registry=registry,
            worker_id="worker-b",
            now=self.now,
        )

        event.refresh_from_db()
        self.assertEqual(reclaimed["dispatched"], 1)
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.SENT)
        self.assertEqual(len(handler.calls), 1)

    def test_two_workers_cannot_claim_same_live_event(self):
        event = self._event()

        first = _claim_batch(
            tenant_id=1,
            limit=1,
            worker_id="worker-a",
            now=self.now,
        )
        second = _claim_batch(
            tenant_id=1,
            limit=1,
            worker_id="worker-b",
            now=self.now,
        )

        self.assertEqual(first, [event.id])
        self.assertEqual(second, [])

    def test_sent_event_is_idempotently_skipped_on_later_runs(self):
        event = self._event()
        handler = _Handler(DispatchResult.ack("stable-receipt"))
        registry = self._registry("StaffActivated", handler)

        first = dispatch_pending(
            tenant_id=1,
            registry=registry,
            worker_id="worker-a",
            now=self.now,
        )
        second = dispatch_pending(
            tenant_id=1,
            registry=registry,
            worker_id="worker-b",
            now=self.now + timedelta(minutes=5),
        )

        event.refresh_from_db()
        self.assertEqual(first["dispatched"], 1)
        self.assertEqual(second["total"], 0)
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual(event.attempts, 1)

    def test_tenant_filter_never_claims_another_school_event(self):
        event_1 = self._event(tenant_id=1)
        event_2 = self._event(tenant_id=2)
        handler = _Handler(DispatchResult.ack("tenant-receipt"))

        dispatch_pending(
            tenant_id=1,
            registry=self._registry("StaffActivated", handler),
            worker_id="worker-a",
            now=self.now,
        )

        event_1.refresh_from_db()
        event_2.refresh_from_db()
        self.assertEqual(event_1.status, HrOnboardingOutboxEvent.Status.SENT)
        self.assertEqual(event_2.status, HrOnboardingOutboxEvent.Status.PENDING)
        self.assertEqual(len(handler.calls), 1)
