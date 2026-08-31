import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from hr_payroll import api
from hr_payroll.calculation_models import PayrollPaymentInstruction
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.services.payment_service import PayrollPaymentError, PayrollPaymentService


class TrustedSandboxPaymentProvider:
    dispatch_calls = []

    def dispatch(self, request):
        self.__class__.dispatch_calls.append(request)
        return {
            "tenantId": request["tenantId"],
            "instructionId": request["instructionId"],
            "instructionNo": request["instructionNo"],
            "providerCode": request["providerCode"],
            "requestedAmount": request["requestedAmount"],
            "currencyCode": request["currencyCode"],
            "idempotencyKey": request["idempotencyKey"],
            "dispatchReceiptId": "dispatch-001",
            "status": "SENT",
        }

    def verify_receipt(self, payload):
        # A production adapter performs signature/authentication here and only
        # returns a normalized mapping after that verification succeeds.
        return dict(payload)


class TamperedAmountPaymentProvider(TrustedSandboxPaymentProvider):
    def dispatch(self, request):
        result = super().dispatch(request)
        result["requestedAmount"] = "0.01"
        return result


class UnavailablePaymentProvider(TrustedSandboxPaymentProvider):
    def dispatch(self, request):
        raise TimeoutError("sandbox provider timeout")


class _User:
    is_authenticated = True
    is_superuser = False
    id = 901

    def has_perm(self, permission):
        return permission == api.PERM_PAYMENT


class PaymentProviderBoundaryTests(TestCase):
    tenant_id = 77
    staff_id = uuid.UUID("00000000-0000-0000-0000-000000001501")

    def setUp(self):
        TrustedSandboxPaymentProvider.dispatch_calls.clear()
        self.period = PayrollPeriod.objects.create(
            tenant_id=self.tenant_id,
            period_code="2026-08",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status=PayrollPeriod.Status.FINALIZED,
        )
        self.result = PayrollResultFact.objects.create(
            tenant_id=self.tenant_id,
            result_no="PAY-RESULT-001",
            payroll_period_id=self.period.id,
            staff_id=self.staff_id,
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("1200.00"),
            net_amount=Decimal("8800.00"),
            status=PayrollResultFact.Status.FINALIZED,
        )
        PayrollProfile.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff_id,
            payroll_identity_no="PAY-ID-1501",
            pay_group_code="FACULTY",
            currency_code="CNY",
            payment_account_ref="vault://payroll/1501",
            effective_from=date(2026, 1, 1),
        )
        self.service = PayrollPaymentService(self.tenant_id, actor_user_id=901)
        self.instruction = self.service.create_instruction(
            result_id=self.result.id,
            instruction_no="PAYMENT-2026-08-1501",
            provider_code="SANDBOX_BANK",
        )

    def _receipt(self, **updates):
        payload = {
            "tenantId": self.tenant_id,
            "instructionId": str(self.instruction.id),
            "instructionNo": self.instruction.instruction_no,
            "providerCode": self.instruction.provider_code,
            "receiptNo": "BANK-RECEIPT-1501",
            "status": "ACCEPTED",
            "settledAmount": "8800.00",
            "currencyCode": "CNY",
            "idempotencyKey": f"hr15:{self.tenant_id}:{self.instruction.id}",
        }
        payload.update(updates)
        return payload

    def test_unconfigured_provider_fails_closed_without_marking_sent(self):
        with self.assertRaises(PayrollPaymentError) as caught:
            self.service.dispatch(instruction_id=self.instruction.id)

        self.assertEqual(caught.exception.code, "PAYROLL_PAYMENT_PROVIDER_UNAVAILABLE")
        self.instruction.refresh_from_db()
        self.assertEqual(self.instruction.status, PayrollPaymentInstruction.Status.CREATED)

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TrustedSandboxPaymentProvider"
            )
        }
    )
    def test_dispatch_uses_provider_contract_and_is_idempotent(self):
        sent = self.service.dispatch(instruction_id=self.instruction.id)
        replay = self.service.dispatch(instruction_id=self.instruction.id)

        self.assertEqual(sent.status, PayrollPaymentInstruction.Status.SENT)
        self.assertEqual(replay.id, sent.id)
        self.assertEqual(len(TrustedSandboxPaymentProvider.dispatch_calls), 1)
        self.assertEqual(
            sent.provider_receipt_json["dispatch"]["dispatchReceiptId"],
            "dispatch-001",
        )
        self.assertNotIn("vault://", json.dumps(sent.provider_receipt_json))

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TamperedAmountPaymentProvider"
            )
        }
    )
    def test_tampered_dispatch_response_never_marks_instruction_sent(self):
        with self.assertRaises(PayrollPaymentError) as caught:
            self.service.dispatch(instruction_id=self.instruction.id)

        self.assertEqual(caught.exception.code, "PAYROLL_PAYMENT_PROVIDER_CONTRACT_INVALID")
        self.instruction.refresh_from_db()
        self.assertEqual(self.instruction.status, PayrollPaymentInstruction.Status.CREATED)

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "UnavailablePaymentProvider"
            )
        }
    )
    def test_provider_timeout_is_retryable_without_fake_sent_state(self):
        with self.assertRaises(PayrollPaymentError) as caught:
            self.service.dispatch(instruction_id=self.instruction.id)

        self.assertEqual(caught.exception.code, "PAYROLL_PAYMENT_PROVIDER_UNAVAILABLE")
        self.instruction.refresh_from_db()
        self.assertEqual(self.instruction.status, PayrollPaymentInstruction.Status.CREATED)
        self.assertEqual(
            self.instruction.provider_receipt_json["dispatchClaim"]["state"],
            "FAILED",
        )

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TrustedSandboxPaymentProvider"
            )
        }
    )
    def test_only_verified_provider_receipt_can_accept_payment(self):
        self.service.dispatch(instruction_id=self.instruction.id)
        accepted = self.service.ingest_provider_receipt(
            instruction_id=self.instruction.id,
            provider_payload=self._receipt(),
        )

        self.assertEqual(accepted.status, PayrollPaymentInstruction.Status.ACCEPTED)
        self.assertEqual(
            accepted.provider_receipt_json["receipt"]["receiptNo"],
            "BANK-RECEIPT-1501",
        )

        replay = self.service.ingest_provider_receipt(
            instruction_id=self.instruction.id,
            provider_payload=self._receipt(),
        )
        self.assertEqual(replay.id, accepted.id)

        with self.assertRaises(PayrollPaymentError) as caught:
            self.service.ingest_provider_receipt(
                instruction_id=self.instruction.id,
                provider_payload=self._receipt(receiptNo="BANK-RECEIPT-CHANGED"),
            )
        self.assertEqual(caught.exception.code, "PAYROLL_PAYMENT_RECEIPT_CONFLICT")

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TrustedSandboxPaymentProvider"
            )
        }
    )
    def test_mismatched_tenant_amount_currency_or_instruction_is_rejected(self):
        self.service.dispatch(instruction_id=self.instruction.id)
        invalid_payloads = (
            self._receipt(tenantId=78),
            self._receipt(instructionId=str(uuid.uuid4())),
            self._receipt(settledAmount="8799.99"),
            self._receipt(currencyCode="USD"),
            self._receipt(status="REJECTED", settledAmount="1.00"),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(PayrollPaymentError) as caught:
                    self.service.ingest_provider_receipt(
                        instruction_id=self.instruction.id,
                        provider_payload=payload,
                    )
                self.assertEqual(
                    caught.exception.code,
                    "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                )
        self.instruction.refresh_from_db()
        self.assertEqual(self.instruction.status, PayrollPaymentInstruction.Status.SENT)

    @override_settings(
        HR15_PAYMENT_PROVIDERS={
            "SANDBOX_BANK": (
                "hr_payroll.tests.test_payment_provider_boundary."
                "TrustedSandboxPaymentProvider"
            )
        }
    )
    @patch("hr_payroll.services.payment_service.emit_registered_event")
    def test_event_failure_rolls_back_trusted_receipt(self, emit_event):
        self.service.dispatch(instruction_id=self.instruction.id)
        emit_event.side_effect = RuntimeError("outbox unavailable")

        with self.assertRaises(RuntimeError):
            self.service.ingest_provider_receipt(
                instruction_id=self.instruction.id,
                provider_payload=self._receipt(),
            )

        self.instruction.refresh_from_db()
        self.assertEqual(self.instruction.status, PayrollPaymentInstruction.Status.SENT)

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.PayrollPaymentService")
    def test_business_receipt_api_is_closed(self, service_cls, _allowed, _tenant):
        request = RequestFactory().post(
            f"/api/v1/hr/payroll/payments/{self.instruction.id}/receipts/",
            data=json.dumps(self._receipt()),
            content_type="application/json",
        )
        request.user = _User()

        response = api.receive_payment(request, self.instruction.id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "PAYROLL_PAYMENT_TRUSTED_RECEIPT_REQUIRED",
        )
        service_cls.assert_not_called()

    def test_legacy_manual_state_methods_are_fail_closed(self):
        with self.assertRaises(PayrollPaymentError) as sent_error:
            self.service.mark_sent(instruction_id=self.instruction.id)
        self.assertEqual(
            sent_error.exception.code,
            "PAYROLL_PAYMENT_TRUSTED_PROVIDER_REQUIRED",
        )
        with self.assertRaises(PayrollPaymentError) as receipt_error:
            self.service.record_receipt(
                instruction_id=self.instruction.id,
                receipt_no="forged",
                accepted=True,
                settled_amount="8800.00",
            )
        self.assertEqual(
            receipt_error.exception.code,
            "PAYROLL_PAYMENT_TRUSTED_RECEIPT_REQUIRED",
        )
