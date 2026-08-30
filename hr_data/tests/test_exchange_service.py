import uuid
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from hr_data.models import (
    ExchangeAttempt,
    ExchangeDatasetVersion,
    ExchangeDeadLetter,
    ExchangeJob,
    ExchangeReceipt,
    ExchangeReconciliation,
)
from hr_data.services.exchange_service import (
    ExchangeDefinitionService,
    ExchangeError,
    ExchangeJobService,
)


PROVIDER_CALLS = []


def successful_provider(**kwargs):
    PROVIDER_CALLS.append(
        {
            "tenant_id": kwargs["tenant_id"],
            "job_id": str(kwargs["job"].id),
            "idempotency_key": kwargs["idempotency_key"],
            "payload_hash": kwargs["dataset"].payload_hash,
            "inside_transaction": connection.in_atomic_block,
        }
    )
    return {
        "transmitted": True,
        "dispatchRef": f"remote-{kwargs['job'].id}",
        "providerVersion": "sandbox-1",
    }


def failing_provider(**_kwargs):
    raise RuntimeError("https://secret-target.invalid?token=do-not-store")


class ExchangeRuntimeTests(TransactionTestCase):
    tenant_id = 77
    payload_hash = "a" * 64

    def setUp(self):
        PROVIDER_CALLS.clear()
        self.definitions = ExchangeDefinitionService(self.tenant_id, actor_user_id=9)

    def _definitions(self, *, provider_key="SANDBOX"):
        dataset = self.definitions.create_dataset_version(
            dataset_code="STAFF_ROSTER",
            name="Staff roster",
            schema={"fields": [{"name": "staffNo", "type": "string"}]},
            source_snapshot={"HR03": {"status": "COMPLETE", "evidenceHash": "b" * 64}},
            payload_ref="secure://hr18/roster/2026-08",
            payload_hash=self.payload_hash,
            record_count=12,
        ).value
        target = self.definitions.create_target_mapping_version(
            target_code="EDU_AUTHORITY",
            dataset_code=dataset.dataset_code,
            dataset_version=dataset.version_no,
            transport_kind="HTTPS",
            provider_key=provider_key,
            mapping={"staffNo": "person_id"},
        ).value
        return dataset, target

    def _job(self, *, max_attempts=5, provider_key="SANDBOX"):
        dataset, target = self._definitions(provider_key=provider_key)
        job = ExchangeJobService(self.tenant_id, actor_user_id=9).queue(
            job_no=f"JOB_{uuid.uuid4().hex[:12].upper()}",
            dataset_version_id=dataset.id,
            target_mapping_version_id=target.id,
            idempotency_key=f"idem-{uuid.uuid4()}",
            max_attempts=max_attempts,
        ).value
        return dataset, target, job

    def test_dataset_is_versioned_idempotent_and_immutable(self):
        dataset, _target = self._definitions()
        replay = self.definitions.create_dataset_version(
            dataset_code="STAFF_ROSTER",
            name="Staff roster",
            schema={"fields": [{"name": "staffNo", "type": "string"}]},
            source_snapshot={"HR03": {"status": "COMPLETE", "evidenceHash": "b" * 64}},
            payload_ref="secure://hr18/roster/2026-08",
            payload_hash=self.payload_hash,
            record_count=12,
            frozen_at=dataset.frozen_at,
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.value.id, dataset.id)
        dataset.payload_hash = "c" * 64
        with self.assertRaisesRegex(ValueError, "EXCHANGE_DATASET_IMMUTABLE"):
            dataset.save()

    def test_mapping_rejects_embedded_transport_secrets(self):
        dataset = self.definitions.create_dataset_version(
            dataset_code="STAFF_ROSTER",
            name="Staff roster",
            schema={"fields": ["staffNo"]},
            source_snapshot={"HR03": {"status": "COMPLETE"}},
            payload_ref="secure://payload",
            payload_hash=self.payload_hash,
            record_count=1,
        ).value
        with self.assertRaises(ExchangeError) as ctx:
            self.definitions.create_target_mapping_version(
                target_code="TARGET_ONE",
                dataset_code=dataset.dataset_code,
                dataset_version=dataset.version_no,
                transport_kind="HTTPS",
                provider_key="SANDBOX",
                mapping={"token": "plaintext-secret"},
            )
        self.assertEqual(ctx.exception.code, "EXCHANGE_MAPPING_SECRET_FORBIDDEN")

    def test_queue_is_tenant_scoped_and_idempotency_conflicts_fail_closed(self):
        dataset, target = self._definitions()
        service = ExchangeJobService(self.tenant_id)
        first = service.queue(
            job_no="JOB_FIRST",
            dataset_version_id=dataset.id,
            target_mapping_version_id=target.id,
            idempotency_key="same-command",
        )
        replay = service.queue(
            job_no="JOB_REPLAY",
            dataset_version_id=dataset.id,
            target_mapping_version_id=target.id,
            idempotency_key="same-command",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.value.id, first.value.id)
        with self.assertRaises(ExchangeError) as ctx:
            ExchangeJobService(88).queue(
                job_no="JOB_CROSS_TENANT",
                dataset_version_id=dataset.id,
                target_mapping_version_id=target.id,
                idempotency_key="cross-tenant",
            )
        self.assertEqual(ctx.exception.code, "EXCHANGE_DEFINITION_NOT_FOUND")

    @override_settings(
        HR18_EXCHANGE_PROVIDERS={
            "SANDBOX": "hr_data.tests.test_exchange_service.successful_provider"
        }
    )
    def test_provider_runs_outside_transaction_and_success_is_ledgered(self):
        _dataset, _target, job = self._job()
        result = ExchangeJobService(self.tenant_id, actor_user_id=9).dispatch(job.id)
        self.assertTrue(result.transmitted)
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.TRANSMITTED)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(len(PROVIDER_CALLS), 1)
        self.assertFalse(PROVIDER_CALLS[0]["inside_transaction"])
        self.assertEqual(PROVIDER_CALLS[0]["payload_hash"], self.payload_hash)
        self.assertTrue(PROVIDER_CALLS[0]["idempotency_key"].endswith(":1"))
        attempt = ExchangeAttempt.objects.get(job_id=job.id)
        self.assertEqual(attempt.status, ExchangeAttempt.Status.TRANSMITTED)
        with self.assertRaisesRegex(ValueError, "EXCHANGE_ATTEMPT_IMMUTABLE"):
            attempt.save()

    def test_missing_provider_is_explicitly_unavailable_and_does_not_claim(self):
        _dataset, _target, job = self._job(provider_key="NOT_CONFIGURED")
        with self.assertRaises(ExchangeError) as ctx:
            ExchangeJobService(self.tenant_id).dispatch(job.id)
        self.assertEqual(ctx.exception.code, "EXCHANGE_PROVIDER_UNAVAILABLE")
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.QUEUED)
        self.assertEqual(job.attempt_count, 0)

    @override_settings(
        HR18_EXCHANGE_PROVIDERS={
            "SANDBOX": "hr_data.tests.test_exchange_service.failing_provider"
        }
    )
    def test_failures_retry_then_enter_immutable_dead_letter_without_secret_leak(self):
        _dataset, _target, job = self._job(max_attempts=2)
        service = ExchangeJobService(self.tenant_id)
        first = service.dispatch(job.id)
        self.assertTrue(first.retry_scheduled)
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.RETRY_WAIT)
        self.assertEqual(job.last_error_code, "PROVIDER_RUNTIMEERROR")
        self.assertNotIn("token", job.last_error_code)
        job.next_attempt_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["next_attempt_at", "updated_at"])
        second = service.dispatch(job.id)
        self.assertTrue(second.dead_lettered)
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.DEAD_LETTER)
        dead = ExchangeDeadLetter.objects.get(job_id=job.id)
        self.assertEqual(dead.final_attempt_no, 2)
        self.assertEqual(dead.snapshot_hash, self.payload_hash)
        self.assertEqual(ExchangeAttempt.objects.filter(job_id=job.id).count(), 2)

    @override_settings(
        HR18_EXCHANGE_PROVIDERS={
            "SANDBOX": "hr_data.tests.test_exchange_service.successful_provider"
        }
    )
    def test_receipt_and_matching_reconciliation_complete_exactly_once(self):
        dataset, _target, job = self._job()
        service = ExchangeJobService(self.tenant_id)
        service.dispatch(job.id)
        receipt = service.record_receipt(
            job.id,
            receipt_ref="receipt-001",
            accepted=True,
            received_payload_hash=dataset.payload_hash,
            received_record_count=dataset.record_count,
            receipt_evidence={"signedBy": "sandbox"},
        )
        replay = service.record_receipt(
            job.id,
            receipt_ref="receipt-001",
            accepted=True,
            received_payload_hash=dataset.payload_hash,
            received_record_count=dataset.record_count,
            receipt_evidence={"signedBy": "sandbox"},
        )
        self.assertTrue(receipt.created)
        self.assertFalse(replay.created)
        with self.assertRaisesRegex(ValueError, "EXCHANGE_RECEIPT_IMMUTABLE"):
            receipt.value.save()
        outcome = service.reconcile(job.id)
        self.assertEqual(outcome.value.status, ExchangeReconciliation.Status.MATCHED)
        with self.assertRaisesRegex(ValueError, "EXCHANGE_RECONCILIATION_IMMUTABLE"):
            outcome.value.save()
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.RECONCILED)
        self.assertEqual(ExchangeReceipt.objects.filter(job_id=job.id).count(), 1)
        second = service.reconcile(job.id)
        self.assertFalse(second.created)

    @override_settings(
        HR18_EXCHANGE_PROVIDERS={
            "SANDBOX": "hr_data.tests.test_exchange_service.successful_provider"
        }
    )
    def test_reconciliation_mismatch_enters_failure_queue(self):
        _dataset, _target, job = self._job()
        service = ExchangeJobService(self.tenant_id)
        service.dispatch(job.id)
        service.record_receipt(
            job.id,
            receipt_ref="receipt-mismatch",
            accepted=True,
            received_payload_hash="f" * 64,
            received_record_count=999,
            receipt_evidence={"signed": True},
        )
        outcome = service.reconcile(job.id)
        self.assertEqual(outcome.value.status, ExchangeReconciliation.Status.MISMATCH)
        self.assertIn("payloadHash", outcome.value.differences_json)
        job.refresh_from_db()
        self.assertEqual(job.status, ExchangeJob.Status.DEAD_LETTER)
        self.assertTrue(ExchangeDeadLetter.objects.filter(job_id=job.id).exists())

    def test_stale_worker_cannot_overwrite_new_lease(self):
        _dataset, _target, job = self._job()
        service = ExchangeJobService(self.tenant_id)
        _job1, lease1, started1 = service._claim(job.id, lease_seconds=1)
        ExchangeJob.objects.filter(id=job.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        _job2, lease2, _started2 = service._claim(job.id, lease_seconds=300)
        self.assertNotEqual(lease1, lease2)
        with self.assertRaises(ExchangeError) as ctx:
            service._record_success(
                job.id,
                lease_token=lease1,
                attempt_key="stale-attempt",
                started_at=started1,
                dispatch_ref="stale-ref",
                provider_version="old",
                response_hash="b" * 64,
            )
        self.assertEqual(ctx.exception.code, "EXCHANGE_LEASE_LOST")
        job.refresh_from_db()
        self.assertEqual(job.lease_token, lease2)
        self.assertEqual(job.status, ExchangeJob.Status.LEASED)
