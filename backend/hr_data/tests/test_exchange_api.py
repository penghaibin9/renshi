import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import exchange_api
from hr_data.api import HrDataAccessError


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

