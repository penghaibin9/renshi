import uuid
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings

from hr_data.models import SubmissionSnapshot
from hr_data.services.submission_dispatch_service import (
    SubmissionDispatchError,
    SubmissionDispatchService,
)


DISPATCH_CALLS = []


def successful_dispatch_provider(*, tenant_id, submission, idempotency_key, actor_user_id=None):
    DISPATCH_CALLS.append((tenant_id, str(submission.id), idempotency_key, actor_user_id))
    return {"queued": True, "dispatchRef": f"dispatch-{submission.id}"}


def failing_dispatch_provider(**_kwargs):
    raise RuntimeError("message broker unavailable")


def invalid_dispatch_provider(**_kwargs):
    return {"queued": True}


class SubmissionDispatchServiceTests(TestCase):
    def setUp(self):
        DISPATCH_CALLS.clear()

    def _snapshot(self, *, status=SubmissionSnapshot.Status.APPROVED):
        return SubmissionSnapshot.objects.create(
            tenant_id=77,
            submission_no=f"SUB-{uuid.uuid4().hex[:8]}",
            definition_code="ACTIVE_STAFF_COUNT",
            definition_version=3,
            as_of_date=date(2026, 8, 1),
            scope_json={"asOfEvidenceId": str(uuid.uuid4())},
            payload_hash="a" * 64,
            status=status,
        )

    def test_missing_provider_keeps_approved_state(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as ctx:
            SubmissionDispatchService(77).queue(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_DISPATCH_UNAVAILABLE")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.APPROVED)
        self.assertEqual(snapshot.dispatch_ref, "")

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.successful_dispatch_provider"
        )
    )
    def test_successful_provider_only_queues_and_persists_durable_ref(self):
        snapshot = self._snapshot()
        result = SubmissionDispatchService(77, actor_user_id=9).queue(snapshot.id)

        self.assertTrue(result.queued)
        self.assertTrue(result.dispatch_ref.startswith("dispatch-"))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DISPATCH_QUEUED)
        self.assertEqual(snapshot.dispatch_ref, result.dispatch_ref)
        self.assertIsNotNone(snapshot.dispatch_requested_at)
        self.assertIsNone(snapshot.submitted_at)
        self.assertEqual(snapshot.dispatch_error, "")
        self.assertEqual(len(DISPATCH_CALLS), 1)
        self.assertIn(str(snapshot.id), DISPATCH_CALLS[0][2])
        self.assertIn(snapshot.payload_hash, DISPATCH_CALLS[0][2])

        replay = SubmissionDispatchService(77, actor_user_id=99).queue(snapshot.id)
        self.assertFalse(replay.queued)
        self.assertEqual(replay.dispatch_ref, result.dispatch_ref)
        self.assertEqual(len(DISPATCH_CALLS), 1)

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.failing_dispatch_provider"
        )
    )
    def test_provider_exception_becomes_retryable_dispatch_failed(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as ctx:
            SubmissionDispatchService(77).queue(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_DISPATCH_FAILED")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DISPATCH_FAILED)
        self.assertIn("message broker unavailable", snapshot.dispatch_error)
        self.assertEqual(snapshot.dispatch_ref, "")

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.successful_dispatch_provider"
        )
    )
    def test_failed_snapshot_can_be_requeued_with_same_payload_idempotency(self):
        snapshot = self._snapshot(status=SubmissionSnapshot.Status.DISPATCH_FAILED)
        snapshot.dispatch_error = "old failure"
        snapshot.save(update_fields=["dispatch_error", "updated_at"])

        result = SubmissionDispatchService(77).queue(snapshot.id)

        self.assertTrue(result.queued)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DISPATCH_QUEUED)
        self.assertEqual(snapshot.dispatch_error, "")

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.invalid_dispatch_provider"
        )
    )
    def test_invalid_provider_contract_cannot_fake_queue_success(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as ctx:
            SubmissionDispatchService(77).queue(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_DISPATCH_CONTRACT_INVALID")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.APPROVED)
        self.assertEqual(snapshot.dispatch_ref, "")

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.successful_dispatch_provider"
        )
    )
    def test_cross_tenant_submission_cannot_be_queued(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as ctx:
            SubmissionDispatchService(88).queue(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_NOT_FOUND")
        self.assertEqual(DISPATCH_CALLS, [])
