import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from hr_data.models import (
    SubmissionDispatchAttempt,
    SubmissionDispatchEvent,
    SubmissionDispatchJob,
    SubmissionSnapshot,
    SubmissionTrustedReceipt,
)
from hr_data.services.submission_dispatch_service import (
    SubmissionDispatchError,
    SubmissionDispatchService,
)


DISPATCH_CALLS = []


class TrustedSubmissionAdapter:
    def dispatch(self, *, tenant_id, submission_manifest, idempotency_key, actor_user_id=None):
        DISPATCH_CALLS.append(idempotency_key)
        return {
            "dispatched": True,
            "tenantId": tenant_id,
            "submissionId": submission_manifest["submissionId"],
            "schemaVersion": submission_manifest["schemaVersion"],
            "definitionVersion": submission_manifest["definitionVersion"],
            "payloadHash": submission_manifest["payloadHash"],
            "dispatchRef": f"external-{submission_manifest['submissionId']}",
            "providerVersion": "trusted-adapter-v1",
        }

    def verify_receipt(self, *, tenant_id, submission_manifest, receipt_payload):
        if receipt_payload.get("signature") != "valid-platform-signature":
            raise ValueError("signature rejected")
        accepted = receipt_payload.get("signedOutcome") == "ACCEPTED"
        return {
            "verified": True,
            "tenantId": tenant_id,
            "submissionId": submission_manifest["submissionId"],
            "schemaVersion": submission_manifest["schemaVersion"],
            "definitionVersion": submission_manifest["definitionVersion"],
            "payloadHash": submission_manifest["payloadHash"],
            "dispatchRef": receipt_payload["dispatchRef"],
            "accepted": accepted,
            "receiptRef": receipt_payload["receiptRef"],
            "providerVersion": "trusted-adapter-v1",
            "receiptHash": receipt_payload["receiptHash"],
            "signatureKeyId": "platform-key-2026",
        }


class FailingSubmissionAdapter(TrustedSubmissionAdapter):
    def dispatch(self, **kwargs):
        DISPATCH_CALLS.append(kwargs["idempotency_key"])
        raise RuntimeError("https://secret.internal/?token=secret delivery failed")


class MismatchedSubmissionAdapter(TrustedSubmissionAdapter):
    def dispatch(self, **kwargs):
        value = super().dispatch(**kwargs)
        value["payloadHash"] = "b" * 64
        return value


class NoVerifierAdapter:
    def dispatch(self, **kwargs):
        return TrustedSubmissionAdapter().dispatch(**kwargs)


TRUSTED_SETTINGS = {
    "HR18_SUBMISSION_DISPATCH_PROVIDER": (
        "hr_data.tests.test_submission_dispatch.TrustedSubmissionAdapter"
    ),
    "HR18_SUBMISSION_DISPATCH_PROVIDER_KEY": "EDU_PLATFORM",
}


@override_settings(**TRUSTED_SETTINGS)
class SubmissionDispatchServiceTests(TestCase):
    def setUp(self):
        DISPATCH_CALLS.clear()

    def _snapshot(self, *, tenant_id=77, status=SubmissionSnapshot.Status.APPROVED):
        return SubmissionSnapshot.objects.create(
            tenant_id=tenant_id,
            submission_no=f"SUB-{uuid.uuid4().hex[:8]}",
            definition_code="ACTIVE_STAFF_COUNT",
            definition_version=3,
            as_of_date=date(2026, 8, 1),
            scope_json={"asOfEvidenceId": str(uuid.uuid4())},
            payload_hash="a" * 64,
            status=status,
        )

    def _queued(self):
        snapshot = self._snapshot()
        result = SubmissionDispatchService(77, actor_user_id=9).queue(snapshot.id)
        return snapshot, result, SubmissionDispatchJob.objects.get(submission=snapshot)

    def _submitted(self):
        snapshot, _result, job = self._queued()
        outcome = SubmissionDispatchService(77, actor_user_id=9).dispatch(job.id)
        snapshot.refresh_from_db()
        job.refresh_from_db()
        self.assertTrue(outcome.submitted)
        return snapshot, job

    @override_settings(HR18_SUBMISSION_DISPATCH_PROVIDER="")
    def test_missing_provider_keeps_approved_state(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as caught:
            SubmissionDispatchService(77).queue(snapshot.id)
        self.assertEqual(caught.exception.code, "SUBMISSION_DISPATCH_UNAVAILABLE")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.APPROVED)
        self.assertFalse(SubmissionDispatchJob.objects.exists())

    def test_http_queue_only_appends_job_and_event_then_stably_replays(self):
        snapshot, result, job = self._queued()
        snapshot.refresh_from_db()
        self.assertTrue(result.queued)
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DISPATCH_QUEUED)
        self.assertEqual(DISPATCH_CALLS, [])
        self.assertEqual(job.status, SubmissionDispatchJob.Status.QUEUED)
        self.assertEqual(job.payload_hash, snapshot.payload_hash)
        self.assertEqual(len(job.request_hash), 64)
        self.assertEqual(
            SubmissionDispatchEvent.objects.filter(
                submission=snapshot, event_type="hr.data.submission.queued"
            ).count(),
            1,
        )

        replay = SubmissionDispatchService(77).queue(snapshot.id)
        self.assertFalse(replay.queued)
        self.assertEqual(replay.dispatch_ref, result.dispatch_ref)
        self.assertEqual(SubmissionDispatchJob.objects.filter(submission=snapshot).count(), 1)

    def test_worker_claims_and_only_verified_adapter_binding_marks_submitted(self):
        snapshot, _result, job = self._queued()
        outcome = SubmissionDispatchService(77, actor_user_id=22).dispatch(job.id)
        self.assertTrue(outcome.submitted)
        snapshot.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.SUBMITTED)
        self.assertEqual(job.status, SubmissionDispatchJob.Status.SUBMITTED)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(SubmissionDispatchAttempt.objects.filter(job=job).count(), 1)
        self.assertEqual(DISPATCH_CALLS, [job.idempotency_key])

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.MismatchedSubmissionAdapter"
        )
    )
    def test_mismatched_adapter_receipt_never_marks_submitted(self):
        snapshot, _result, job = self._queued()
        outcome = SubmissionDispatchService(77).dispatch(job.id)
        self.assertFalse(outcome.submitted)
        self.assertTrue(outcome.retry_scheduled)
        snapshot.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DISPATCH_FAILED)
        self.assertEqual(job.status, SubmissionDispatchJob.Status.RETRY_WAIT)
        self.assertEqual(job.last_error_code, "SUBMISSION_DISPATCH_RECEIPT_MISMATCH")

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.FailingSubmissionAdapter"
        )
    )
    def test_provider_failure_is_redacted_retryable_and_uses_stable_key(self):
        snapshot, _result, job = self._queued()
        outcome = SubmissionDispatchService(77).dispatch(job.id)
        self.assertTrue(outcome.retry_scheduled)
        job.refresh_from_db()
        snapshot.refresh_from_db()
        self.assertNotIn("secret", job.last_error_code.lower())
        self.assertEqual(snapshot.dispatch_error, "submission dispatch failed")
        self.assertEqual(DISPATCH_CALLS, [job.idempotency_key])

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.FailingSubmissionAdapter"
        )
    )
    def test_retry_reuses_external_idempotency_key_and_only_one_success_fact(self):
        snapshot, _result, job = self._queued()
        failed = SubmissionDispatchService(77).dispatch(job.id)
        self.assertTrue(failed.retry_scheduled)
        first_key = DISPATCH_CALLS[-1]
        future = timezone.now() + timedelta(minutes=2)
        with override_settings(**TRUSTED_SETTINGS), mock.patch(
            "hr_data.services.submission_dispatch_service.timezone.now",
            return_value=future,
        ):
            succeeded = SubmissionDispatchService(77).dispatch(job.id)
        self.assertTrue(succeeded.submitted)
        self.assertEqual(DISPATCH_CALLS, [first_key, first_key])
        self.assertEqual(
            SubmissionDispatchAttempt.objects.filter(
                job=job, status=SubmissionDispatchAttempt.Status.DISPATCHED
            ).count(),
            1,
        )

    def test_live_lease_blocks_second_worker_and_expired_lease_is_recoverable(self):
        snapshot, _result, job = self._queued()
        service = SubmissionDispatchService(77)
        claimed, old_token, _started, _manifest = service._claim(job.id)
        with self.assertRaises(SubmissionDispatchError) as caught:
            service._claim(job.id)
        self.assertEqual(caught.exception.code, "SUBMISSION_DISPATCH_NOT_CLAIMABLE")

        claimed.lease_expires_at = timezone.now() - timedelta(seconds=1)
        claimed.save(update_fields=["lease_expires_at", "updated_at"])
        outcome = service.dispatch(job.id)
        self.assertTrue(outcome.submitted)
        with self.assertRaises(SubmissionDispatchError) as stale:
            service._record_success(
                job.id,
                lease_token=old_token,
                started_at=timezone.now(),
                dispatch_ref="stale",
                provider_version="stale",
                response_hash="a" * 64,
            )
        self.assertEqual(stale.exception.code, "SUBMISSION_DISPATCH_LEASE_LOST")

    def test_cross_tenant_submission_cannot_be_queued_or_claimed(self):
        snapshot = self._snapshot()
        with self.assertRaises(SubmissionDispatchError) as caught:
            SubmissionDispatchService(88).queue(snapshot.id)
        self.assertEqual(caught.exception.code, "SUBMISSION_NOT_FOUND")

    def test_client_boolean_cannot_forge_receipt_but_signed_adapter_result_can(self):
        snapshot, job = self._submitted()
        service = SubmissionDispatchService(77, actor_user_id=12)
        with self.assertRaises(SubmissionDispatchError) as caught:
            service.record_verified_receipt(
                snapshot.id,
                receipt_payload={"accepted": True, "receiptRef": "FAKE"},
            )
        self.assertEqual(caught.exception.code, "SUBMISSION_RECEIPT_VERIFICATION_FAILED")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.SUBMITTED)

        with self.assertRaises(SubmissionDispatchError) as mismatched:
            service.record_verified_receipt(
                snapshot.id,
                receipt_payload={
                    "signature": "valid-platform-signature",
                    "signedOutcome": "ACCEPTED",
                    "dispatchRef": "another-submission-dispatch",
                    "receiptRef": "BOUND-WRONG",
                    "receiptHash": "b" * 64,
                },
            )
        self.assertEqual(mismatched.exception.code, "SUBMISSION_RECEIPT_BINDING_MISMATCH")
        with self.assertRaises(SubmissionDispatchError) as cross_tenant:
            SubmissionDispatchService(88).record_verified_receipt(
                snapshot.id,
                receipt_payload={"signed": "anything"},
            )
        self.assertEqual(cross_tenant.exception.code, "SUBMISSION_NOT_FOUND")

        signed = {
            "signature": "valid-platform-signature",
            "signedOutcome": "REJECTED",
            "dispatchRef": job.dispatch_ref,
            "receiptRef": "PLATFORM-R-1",
            "receiptHash": "c" * 64,
        }
        result = service.record_verified_receipt(snapshot.id, receipt_payload=signed)
        self.assertEqual(result.status, SubmissionSnapshot.Status.REJECTED)
        receipt = SubmissionTrustedReceipt.objects.get(submission=snapshot)
        self.assertEqual(receipt.outcome, SubmissionTrustedReceipt.Outcome.REJECTED)
        self.assertEqual(receipt.signature_key_id, "platform-key-2026")

        replay = service.record_verified_receipt(snapshot.id, receipt_payload=signed)
        self.assertEqual(replay.id, snapshot.id)
        self.assertEqual(SubmissionTrustedReceipt.objects.filter(submission=snapshot).count(), 1)
        with self.assertRaises(SubmissionDispatchError) as conflict:
            service.record_verified_receipt(
                snapshot.id,
                receipt_payload={
                    **signed,
                    "receiptRef": "PLATFORM-R-CONFLICT",
                    "receiptHash": "e" * 64,
                },
            )
        self.assertEqual(conflict.exception.code, "SUBMISSION_RECEIPT_IDEMPOTENCY_CONFLICT")

        terminal_replay = service.queue(snapshot.id)
        self.assertFalse(terminal_replay.queued)

    @override_settings(
        HR18_SUBMISSION_DISPATCH_PROVIDER=(
            "hr_data.tests.test_submission_dispatch.NoVerifierAdapter"
        )
    )
    def test_adapter_without_receipt_verifier_fails_closed(self):
        # Queue and dispatch work, but no one can forge the terminal outcome.
        snapshot, _result, job = self._queued()
        SubmissionDispatchService(77).dispatch(job.id)
        with self.assertRaises(SubmissionDispatchError) as caught:
            SubmissionDispatchService(77).record_verified_receipt(
                snapshot.id, receipt_payload={"anything": "client controlled"}
            )
        self.assertEqual(caught.exception.code, "SUBMISSION_RECEIPT_VERIFIER_UNAVAILABLE")

    def test_append_only_receipt_attempt_and_event_reject_orm_tampering(self):
        snapshot, job = self._submitted()
        service = SubmissionDispatchService(77)
        signed = {
            "signature": "valid-platform-signature",
            "signedOutcome": "ACCEPTED",
            "dispatchRef": job.dispatch_ref,
            "receiptRef": "PLATFORM-A-1",
            "receiptHash": "d" * 64,
        }
        service.record_verified_receipt(snapshot.id, receipt_payload=signed)
        with self.assertRaises(ValueError):
            SubmissionTrustedReceipt.objects.filter(submission=snapshot).update(
                outcome="REJECTED"
            )
        with self.assertRaises(ValueError):
            SubmissionDispatchAttempt.objects.filter(job=job).delete()
        with self.assertRaises(ValueError):
            SubmissionDispatchEvent.objects.filter(job=job).update(event_hash="0" * 64)
        with self.assertRaises(ValueError):
            SubmissionDispatchJob.objects.filter(id=job.id).update(payload_hash="0" * 64)
        job.payload_hash = "0" * 64
        with self.assertRaisesRegex(ValueError, "IDENTITY_IMMUTABLE|PARENT_MISMATCH"):
            job.save(update_fields=["payload_hash", "updated_at"])

    def test_mysql_migration_seals_job_and_all_append_only_evidence(self):
        migration = Path(__file__).parents[1] / "migrations" / (
            "0015_submissiondispatchjob_submissiondispatchevent_and_more.py"
        )
        source = migration.read_text(encoding="utf-8")
        self.assertIn("atomic = False", source)
        self.assertIn("hr18_submission_dispatch_job_guard", source)
        self.assertIn("hr18_submission_receipt_guard_insert", source)
        for table in (
            "hr18_submission_dispatch_attempt",
            "hr18_submission_trusted_receipt",
            "hr18_submission_dispatch_event",
        ):
            self.assertIn(table, source)
        self.assertIn("HR18_SUBMISSION_RECEIPT_UNTRUSTED_OR_MISMATCH", source)
