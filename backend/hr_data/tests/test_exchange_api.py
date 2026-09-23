import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import exchange_api
from hr_data.api import HrDataAccessError
from hr_data.services.exchange_service import ExchangeError


class ExchangeApiContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id=9, is_authenticated=True)

    def _post(self, path, payload):
        request = self.factory.post(
            path, data=json.dumps(payload), content_type="application/json"
        )
        request.user = self.user
        return request

    @patch("hr_data.exchange_api.resolve_request_tenant", return_value=77)
    @patch("hr_data.exchange_api.ExchangeJobService")
    def test_queue_endpoint_returns_only_tenant_safe_job_contract(self, service_cls, _tenant):
        job_id = uuid.uuid4()
        service_cls.return_value.queue.return_value = SimpleNamespace(
            created=True,
            value=SimpleNamespace(
                id=job_id,
                job_no="JOB_ROSTER_202608",
                status="QUEUED",
                snapshot_hash="a" * 64,
            ),
        )
        response = exchange_api.queue_job(
            self._post(
                "/api/v1/hr/data/exchange/jobs/",
                {
                    "jobNo": "JOB_ROSTER_202608",
                    "datasetVersionId": str(uuid.uuid4()),
                    "targetMappingVersionId": str(uuid.uuid4()),
                    "idempotencyKey": "client-command-1",
                },
            )
        )
        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)
        self.assertEqual(body["data"]["id"], str(job_id))
        self.assertEqual(body["data"]["status"], "QUEUED")
        self.assertNotIn("payloadRef", body["data"])
        self.assertEqual(response["Cache-Control"], "no-store")
        service_cls.assert_called_once_with(77, 9)

    @patch("hr_data.exchange_api.resolve_request_tenant")
    def test_permission_or_tenant_denial_fails_before_payload_processing(self, tenant):
        tenant.side_effect = HrDataAccessError("PERMISSION_DENIED", "denied")
        response = exchange_api.create_dataset(
            self._post("/api/v1/hr/data/exchange/datasets/", {"payloadRef": "secret"})
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"]["code"], "PERMISSION_DENIED")

    @patch("hr_data.exchange_api.resolve_request_tenant", return_value=77)
    @patch("hr_data.exchange_api.ExchangeJobService")
    def test_receipt_endpoint_never_echoes_raw_receipt_evidence(self, service_cls, _tenant):
        job_id = uuid.uuid4()
        receipt_id = uuid.uuid4()
        service_cls.return_value.record_receipt.return_value = SimpleNamespace(
            created=True,
            value=SimpleNamespace(
                id=receipt_id,
                job_id=job_id,
                receipt_ref="receipt-safe-ref",
                accepted=True,
            ),
        )
        response = exchange_api.record_receipt(
            self._post(
                f"/api/v1/hr/data/exchange/jobs/{job_id}/receipt/",
                {
                    "receiptRef": "receipt-safe-ref",
                    "accepted": True,
                    "receiptEvidence": {"signature": "must-not-be-echoed"},
                },
            ),
            job_id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(b"must-not-be-echoed", response.content)

    @patch("hr_data.exchange_api.resolve_request_tenant", return_value=77)
    @patch("hr_data.exchange_api.ExchangeJobService")
    def test_manual_retry_endpoint_returns_successor_provenance(self, service_cls, _tenant):
        source_id = uuid.uuid4()
        successor_id = uuid.uuid4()
        service_cls.return_value.requeue_dead_letter.return_value = SimpleNamespace(
            created=True,
            value=SimpleNamespace(
                id=successor_id,
                job_no="JOB_RETRY_001",
                status="QUEUED",
                retry_of_job_id=source_id,
            ),
        )
        response = exchange_api.retry_job(
            self._post(
                f"/api/v1/hr/data/exchange/jobs/{source_id}/retry/",
                {
                    "newJobNo": "JOB_RETRY_001",
                    "idempotencyKey": "retry-command-001",
                    "reason": "target endpoint recovered",
                },
            ),
            source_id,
        )
        self.assertEqual(response.status_code, 202)
        body = json.loads(response.content)["data"]
        self.assertEqual(body["id"], str(successor_id))
        self.assertEqual(body["retryOfJobId"], str(source_id))
        service_cls.assert_called_once_with(77, 9)

    @patch("hr_data.exchange_api.resolve_request_tenant", return_value=77)
    @patch("hr_data.exchange_api.ExchangeJobService")
    def test_manual_retry_batch_reports_partial_failure_per_item(self, service_cls, _tenant):
        first = uuid.uuid4()
        second = uuid.uuid4()
        successor = uuid.uuid4()
        service_cls.return_value.requeue_dead_letter.side_effect = [
            SimpleNamespace(
                created=True,
                value=SimpleNamespace(id=successor, job_no="JOB_RETRY_OK"),
            ),
            ExchangeError("EXCHANGE_DEAD_LETTER_ALREADY_RESOLVED", "already resolved"),
        ]
        response = exchange_api.retry_batch(
            self._post(
                "/api/v1/hr/data/exchange/jobs/retry-batch/",
                {
                    "items": [
                        {
                            "jobId": str(first),
                            "newJobNo": "JOB_RETRY_OK",
                            "idempotencyKey": "batch-retry-1",
                            "reason": "target recovered",
                        },
                        {
                            "jobId": str(second),
                            "newJobNo": "JOB_RETRY_CONFLICT",
                            "idempotencyKey": "batch-retry-2",
                            "reason": "target recovered",
                        },
                    ]
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)["data"]
        self.assertEqual(body["requestedCount"], 2)
        self.assertEqual(body["successCount"], 1)
        self.assertEqual(body["failureCount"], 1)
        self.assertTrue(body["partial"])
        self.assertTrue(body["results"][0]["ok"])
        self.assertFalse(body["results"][1]["ok"])
        self.assertEqual(
            body["results"][1]["code"], "EXCHANGE_DEAD_LETTER_ALREADY_RESOLVED"
        )

