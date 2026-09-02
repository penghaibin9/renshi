import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from hr_payroll.providers.payment_http import (
    HttpsPaymentProvider,
    PaymentHttpProviderError,
)


PAYMENT_SETTINGS = {
    "DEBUG": False,
    "HR15_PAYMENT_HTTP_ENDPOINT": "https://finance.example.test/hr/payments",
    "HR15_PAYMENT_HTTP_TOKEN": "finance-provider-token-never-log",
    "HR15_PAYMENT_HTTP_TIMEOUT_SECONDS": 12,
    "HR15_PAYMENT_RECEIPT_HMAC_SECRET": "finance-receipt-secret-with-at-least-32-bytes",
    "HR15_PAYMENT_RECEIPT_KEY_ID": "finance-2026-09",
    "HR15_PAYMENT_PROVIDER_CODE": "UNIVERSITY_FINANCE",
}


@override_settings(**PAYMENT_SETTINGS)
class HttpsPaymentProviderTests(SimpleTestCase):
    request = {
        "tenantId": 77,
        "instructionId": "payment-id",
        "instructionNo": "PAY-2026-09-001",
        "providerCode": "UNIVERSITY_FINANCE",
        "requestedAmount": "8800.00",
        "currencyCode": "CNY",
        "idempotencyKey": "hr15:77:payment-id",
    }

    @patch("hr_payroll.providers.payment_http.requests.post")
    def test_dispatch_is_https_authenticated_tenant_bound_and_idempotent(self, post):
        response = Mock(status_code=202)
        response.json.return_value = {
            "data": {**self.request, "dispatchReceiptId": "dispatch-001", "status": "SENT"}
        }
        post.return_value = response

        result = HttpsPaymentProvider().dispatch(self.request)

        self.assertEqual(result["dispatchReceiptId"], "dispatch-001")
        call = post.call_args.kwargs
        self.assertEqual(call["timeout"], 12.0)
        self.assertEqual(call["headers"]["Idempotency-Key"], self.request["idempotencyKey"])
        self.assertEqual(call["headers"]["X-Tenant-ID"], "77")
        self.assertEqual(call["json"]["paymentInstruction"], self.request)

    def _signed_receipt(self, **updates):
        body = {
            "tenantId": 77,
            "instructionId": "payment-id",
            "instructionNo": "PAY-2026-09-001",
            "providerCode": "UNIVERSITY_FINANCE",
            "receiptNo": "BANK-001",
            "status": "ACCEPTED",
            "settledAmount": "8800.00",
            "currencyCode": "CNY",
            "idempotencyKey": "hr15:77:payment-id",
            "signatureKeyId": "finance-2026-09",
        }
        body.update(updates)
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        receipt_hash = hashlib.sha256(canonical.encode()).hexdigest()
        signature = hmac.new(
            PAYMENT_SETTINGS["HR15_PAYMENT_RECEIPT_HMAC_SECRET"].encode(),
            receipt_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {**body, "receiptHash": receipt_hash, "signature": signature}

    def test_receipt_signature_is_verified_before_normalization(self):
        result = HttpsPaymentProvider().verify_receipt(self._signed_receipt())
        self.assertEqual(result["receiptNo"], "BANK-001")
        self.assertNotIn("signatureKeyId", result)

    def test_tampered_or_wrong_provider_receipt_fails_closed(self):
        tampered = self._signed_receipt()
        tampered["settledAmount"] = "1.00"
        with self.assertRaises(PaymentHttpProviderError):
            HttpsPaymentProvider().verify_receipt(tampered)
        with self.assertRaises(PaymentHttpProviderError):
            HttpsPaymentProvider().verify_receipt(
                self._signed_receipt(providerCode="OTHER")
            )

    @patch("hr_payroll.providers.payment_http.requests.post")
    def test_transport_failure_is_secret_free(self, post):
        post.side_effect = requests.ConnectionError(
            "https://finance.example.test?token=finance-provider-token-never-log"
        )
        with self.assertRaises(PaymentHttpProviderError) as caught:
            HttpsPaymentProvider().dispatch(self.request)
        message = str(caught.exception)
        self.assertNotIn("token", message.lower())
        self.assertNotIn("example.test", message)

    def test_plain_http_is_rejected_outside_local_debug(self):
        with override_settings(HR15_PAYMENT_HTTP_ENDPOINT="http://finance.example.test/pay"):
            with self.assertRaises(PaymentHttpProviderError):
                HttpsPaymentProvider().dispatch(self.request)
