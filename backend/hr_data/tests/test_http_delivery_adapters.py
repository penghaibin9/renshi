import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from hr_data.providers.exchange_http import (
    ExchangeHttpProviderError,
    https_exchange_provider,
)
from hr_data.providers.submission_http import (
    HttpsSubmissionAdapter,
    SubmissionHttpAdapterError,
)


COMMON_SUBMISSION_SETTINGS = {
    "DEBUG": False,
    "HR18_SUBMISSION_HTTP_ENDPOINT": "https://edu.example.test/hr/submissions",
    "HR18_SUBMISSION_HTTP_TOKEN": "provider-token-never-log",
    "HR18_SUBMISSION_HTTP_TIMEOUT_SECONDS": 12,
    "HR18_SUBMISSION_HTTP_PROVIDER_VERSION": "edu-v3",
    "HR18_SUBMISSION_RECEIPT_HMAC_SECRET": "a-strong-test-secret-with-more-than-32-bytes",
    "HR18_SUBMISSION_RECEIPT_KEY_ID": "edu-key-2026-09",
}


@override_settings(**COMMON_SUBMISSION_SETTINGS)
class SubmissionHttpAdapterTests(SimpleTestCase):
    manifest = {
        "tenantId": 77,
        "submissionId": "3f9260ec-640d-4f42-b709-b5d87f253784",
        "submissionNo": "SUB_202609_001",
        "schemaVersion": "hr18.submission.1",
        "definitionKind": "METRIC",
        "definitionCode": "ACTIVE_STAFF_COUNT",
        "definitionVersion": 3,
        "asOfDate": "2026-08-31",
        "scope": {"campus": "MAIN"},
        "payloadHash": "a" * 64,
    }

    @patch("hr_data.providers.submission_http.requests.post")
    def test_dispatch_sends_bounded_authenticated_idempotent_request(self, post):
        response = Mock(status_code=202)
        response.json.return_value = {
            "data": {
                "dispatched": True,
                "tenantId": 77,
                "submissionId": self.manifest["submissionId"],
                "schemaVersion": self.manifest["schemaVersion"],
                "definitionVersion": 3,
                "payloadHash": "a" * 64,
                "dispatchRef": "remote-001",
            }
        }
        post.return_value = response

        result = HttpsSubmissionAdapter().dispatch(
            tenant_id=77,
            submission_manifest=self.manifest,
            idempotency_key="stable-idempotency-key",
            actor_user_id=9,
        )

        self.assertTrue(result["dispatched"])
        self.assertEqual(result["providerVersion"], "edu-v3")
        call = post.call_args
        self.assertEqual(call.kwargs["timeout"], 12.0)
        self.assertEqual(call.kwargs["headers"]["Idempotency-Key"], "stable-idempotency-key")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer provider-token-never-log")
        self.assertEqual(call.kwargs["json"]["submission"], self.manifest)

    def _signed_receipt(self, **updates):
        body = {
            "tenantId": 77,
            "submissionId": self.manifest["submissionId"],
            "schemaVersion": self.manifest["schemaVersion"],
            "definitionVersion": 3,
            "payloadHash": "a" * 64,
            "dispatchRef": "remote-001",
            "receiptRef": "receipt-001",
            "signedOutcome": "ACCEPTED",
            "providerVersion": "edu-v3",
            "signatureKeyId": "edu-key-2026-09",
        }
        body.update(updates)
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        receipt_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        signature = hmac.new(
            COMMON_SUBMISSION_SETTINGS["HR18_SUBMISSION_RECEIPT_HMAC_SECRET"].encode(),
            receipt_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {**body, "receiptHash": receipt_hash, "signature": signature}

    def test_signed_receipt_is_bound_to_frozen_identity_and_outcome(self):
        verified = HttpsSubmissionAdapter().verify_receipt(
            tenant_id=77,
            submission_manifest=self.manifest,
            receipt_payload=self._signed_receipt(),
        )
        self.assertTrue(verified["verified"])
        self.assertTrue(verified["accepted"])
        self.assertEqual(verified["dispatchRef"], "remote-001")
        self.assertEqual(len(verified["receiptHash"]), 64)

    def test_tampered_receipt_and_plain_http_fail_closed(self):
        receipt = self._signed_receipt()
        receipt["signedOutcome"] = "REJECTED"
        with self.assertRaises(SubmissionHttpAdapterError):
            HttpsSubmissionAdapter().verify_receipt(
                tenant_id=77,
                submission_manifest=self.manifest,
                receipt_payload=receipt,
            )
        with override_settings(HR18_SUBMISSION_HTTP_ENDPOINT="http://edu.example.test/submit"):
            with self.assertRaises(SubmissionHttpAdapterError):
                HttpsSubmissionAdapter().dispatch(
                    tenant_id=77,
                    submission_manifest=self.manifest,
                    idempotency_key="key",
                )


@override_settings(
    DEBUG=False,
    HR18_EXCHANGE_HTTP_ENDPOINT="https://edu.example.test/hr/exchange",
    HR18_EXCHANGE_HTTP_TOKEN="exchange-token-never-log",
    HR18_EXCHANGE_HTTP_TIMEOUT_SECONDS=9,
    HR18_EXCHANGE_HTTP_PROVIDER_VERSION="exchange-v2",
)
class ExchangeHttpProviderTests(SimpleTestCase):
    @patch("hr_data.providers.exchange_http.requests.post")
    def test_exchange_manifest_contains_frozen_identity_and_safe_mapping(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {
            "transmitted": True,
            "dispatchRef": "exchange-remote-001",
        }
        post.return_value = response
        job = SimpleNamespace(id="job-id", job_no="JOB_001", snapshot_hash="a" * 64)
        dataset = SimpleNamespace(
            id="dataset-id", dataset_code="STAFF_ROSTER", version_no=2,
            schema_json={"fields": ["staffNo"]},
            source_snapshot_json={"HR03": {"status": "COMPLETE"}},
            payload_ref="secure://hr18/staff/2026-09", payload_hash="a" * 64,
            record_count=12, frozen_at=SimpleNamespace(isoformat=lambda: "2026-09-01T00:00:00+08:00"),
        )
        target = SimpleNamespace(
            id="target-id", target_code="EDU_PLATFORM", version_no=1,
            transport_kind="HTTPS", mapping_json={"staffNo": "person_id"},
            expected_receipt=True,
        )
        result = https_exchange_provider(
            tenant_id=77, job=job, dataset=dataset, target_mapping=target,
            idempotency_key="exchange-key:1", actor_user_id=9,
        )
        self.assertTrue(result["transmitted"])
        self.assertEqual(result["providerVersion"], "exchange-v2")
        call = post.call_args.kwargs
        self.assertEqual(call["timeout"], 9.0)
        self.assertEqual(call["headers"]["Idempotency-Key"], "exchange-key:1")
        self.assertNotIn("token", json.dumps(call["json"]).lower())

    @patch("hr_data.providers.exchange_http.requests.post")
    def test_exchange_transport_error_does_not_expose_endpoint_or_token(self, post):
        post.side_effect = requests.ConnectionError(
            "https://edu.example.test/hr/exchange?token=exchange-token-never-log"
        )
        with self.assertRaises(ExchangeHttpProviderError) as caught:
            https_exchange_provider(
                tenant_id=77,
                job=SimpleNamespace(id="j", job_no="J", snapshot_hash="a" * 64),
                dataset=SimpleNamespace(
                    id="d", dataset_code="D", version_no=1, schema_json={},
                    source_snapshot_json={}, payload_ref="secure://d", payload_hash="a" * 64,
                    record_count=0, frozen_at=SimpleNamespace(isoformat=lambda: "now"),
                ),
                target_mapping=SimpleNamespace(
                    id="t", target_code="T", version_no=1, transport_kind="HTTPS",
                    mapping_json={"a": "b"}, expected_receipt=True,
                ),
                idempotency_key="key",
            )
        self.assertNotIn("token", str(caught.exception).lower())
        self.assertNotIn("example.test", str(caught.exception).lower())

    def test_exchange_plain_http_fails_closed(self):
        with override_settings(HR18_EXCHANGE_HTTP_ENDPOINT="http://edu.example.test/exchange"):
            with self.assertRaises(ExchangeHttpProviderError):
                https_exchange_provider(
                    tenant_id=77,
                    job=SimpleNamespace(id="j", job_no="J", snapshot_hash="a" * 64),
                    dataset=SimpleNamespace(
                        id="d", dataset_code="D", version_no=1, schema_json={},
                        source_snapshot_json={}, payload_ref="secure://d", payload_hash="a" * 64,
                        record_count=0, frozen_at=SimpleNamespace(isoformat=lambda: "now"),
                    ),
                    target_mapping=SimpleNamespace(
                        id="t", target_code="T", version_no=1, transport_kind="HTTPS",
                        mapping_json={"a": "b"}, expected_receipt=True,
                    ),
                    idempotency_key="key",
                )
