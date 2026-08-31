"""HR15 finalized-result payment, payslip and finance reconciliation chain."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_FINANCE_RECONCILED,
    EVENT_PAYMENT_ACCEPTED,
    EVENT_PAYSLIP_PUBLISHED,
)
from hr_payroll.calculation_models import (
    PayrollCalculationLine,
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollPayslipFact,
)
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.services.calculation_service import (
    PayrollCalculationError,
    verify_payroll_result_input_evidence,
)
from hr_payroll.services.payment_provider_registry import (
    PaymentProviderRegistry,
    PaymentProviderRegistryError,
)


class PayrollPaymentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayrollPaymentError("PAYROLL_PAYMENT_AMOUNT_INVALID", "invalid payment amount") from exc
    if not amount.is_finite() or amount < 0:
        raise PayrollPaymentError("PAYROLL_PAYMENT_AMOUNT_INVALID", "invalid payment amount")
    return amount


class PayrollPaymentService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: int | None = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise PayrollPaymentError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    @transaction.atomic
    def create_instruction(
        self, *, result_id, instruction_no: str, provider_code: str
    ) -> PayrollPaymentInstruction:
        instruction_no = str(instruction_no or "").strip()
        provider_code = str(provider_code or "").strip()
        if not instruction_no or not provider_code:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_REFERENCE_REQUIRED",
                "instruction_no and provider_code are required",
            )
        result = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise PayrollPaymentError("PAYROLL_RESULT_NOT_FOUND", "payroll result not found")
        if result.status not in {
            PayrollResultFact.Status.FINALIZED,
            PayrollResultFact.Status.ADJUSTED,
        }:
            raise PayrollPaymentError(
                "PAYROLL_RESULT_NOT_FINAL", "only a finalized payroll result can be paid"
            )
        period = PayrollPeriod.objects.filter(
            id=result.payroll_period_id, tenant_id=self.tenant_id
        ).first()
        if period is None or period.status not in {
            PayrollPeriod.Status.FINALIZED,
            PayrollPeriod.Status.CLOSED,
        }:
            raise PayrollPaymentError(
                "PAYROLL_PERIOD_NOT_FINAL", "payroll period is not finalized"
            )
        profile = (
            PayrollProfile.objects.filter(
                tenant_id=self.tenant_id,
                staff_id=result.staff_id,
                currency_code=result.currency_code,
                status=PayrollProfile.Status.ACTIVE,
                effective_from__lte=period.end_date,
            )
            .order_by("-effective_from", "-created_at")
            .first()
        )
        if profile is None or not profile.payment_account_ref:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_ACCOUNT_UNAVAILABLE",
                "an active payroll profile with a payment account reference is required",
            )
        existing = PayrollPaymentInstruction.objects.filter(
            tenant_id=self.tenant_id, payroll_result_id=result.id
        ).first()
        if existing:
            if existing.instruction_no != instruction_no or existing.provider_code != provider_code:
                raise PayrollPaymentError(
                    "PAYROLL_PAYMENT_IDEMPOTENCY_CONFLICT",
                    "result already has another payment instruction",
                )
            return existing
        return PayrollPaymentInstruction.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            instruction_no=instruction_no,
            payroll_result_id=result.id,
            staff_id=result.staff_id,
            currency_code=result.currency_code,
            requested_amount=result.net_amount,
            account_ref_hash=_hash({"tenant": self.tenant_id, "ref": profile.payment_account_ref}),
            status=PayrollPaymentInstruction.Status.CREATED,
            provider_code=provider_code,
        )

    @staticmethod
    def _idempotency_key(instruction: PayrollPaymentInstruction) -> str:
        return f"hr15:{instruction.tenant_id}:{instruction.id}"

    def _dispatch_request(self, instruction: PayrollPaymentInstruction) -> dict:
        return {
            "schemaVersion": "hr15.payment-dispatch.1",
            "tenantId": int(instruction.tenant_id),
            "instructionId": str(instruction.id),
            "instructionNo": instruction.instruction_no,
            "payrollResultId": str(instruction.payroll_result_id),
            "staffId": str(instruction.staff_id),
            "providerCode": instruction.provider_code,
            "requestedAmount": str(_money(instruction.requested_amount)),
            "currencyCode": instruction.currency_code,
            "accountRefHash": instruction.account_ref_hash,
            "idempotencyKey": self._idempotency_key(instruction),
            "correlationId": self.correlation_id,
        }

    @transaction.atomic
    def _claim_dispatch(self, instruction_id):
        instruction = self._lock_instruction(instruction_id)
        if instruction.status == PayrollPaymentInstruction.Status.SENT:
            return instruction, None, None
        if instruction.status in {
            PayrollPaymentInstruction.Status.ACCEPTED,
            PayrollPaymentInstruction.Status.REJECTED,
        }:
            return instruction, None, None
        if instruction.status != PayrollPaymentInstruction.Status.CREATED:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_INVALID_STATE", "payment instruction cannot be dispatched"
            )
        current = instruction.provider_receipt_json or {}
        claim = current.get("dispatchClaim") if isinstance(current, Mapping) else None
        if isinstance(claim, Mapping) and claim.get("state") == "RUNNING":
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_DISPATCH_IN_PROGRESS",
                "payment provider dispatch already has an active claim",
            )
        request_payload = self._dispatch_request(instruction)
        lease_token = uuid.uuid4().hex
        instruction.provider_receipt_json = {
            "dispatchClaim": {
                "state": "RUNNING",
                "leaseToken": lease_token,
                "claimedAt": timezone.now().isoformat(),
                "idempotencyKey": request_payload["idempotencyKey"],
                "requestHash": _hash(request_payload),
            }
        }
        instruction.updated_by = self.actor_user_id
        instruction.save(
            update_fields=["provider_receipt_json", "updated_by", "updated_at"]
        )
        return instruction, request_payload, lease_token

    @transaction.atomic
    def _release_dispatch_claim(self, instruction_id, lease_token: str, *, error: str):
        instruction = self._lock_instruction(instruction_id)
        if instruction.status != PayrollPaymentInstruction.Status.CREATED:
            return instruction
        current = instruction.provider_receipt_json or {}
        claim = current.get("dispatchClaim") if isinstance(current, Mapping) else None
        if not isinstance(claim, Mapping) or claim.get("leaseToken") != lease_token:
            return instruction
        instruction.provider_receipt_json = {
            "dispatchClaim": {
                **dict(claim),
                "state": "FAILED",
                "failedAt": timezone.now().isoformat(),
                "error": str(error or "provider dispatch failed")[:500],
            }
        }
        instruction.updated_by = self.actor_user_id
        instruction.save(
            update_fields=["provider_receipt_json", "updated_by", "updated_at"]
        )
        return instruction

    @staticmethod
    def _require_mapping(value, *, code: str, message: str) -> Mapping:
        if not isinstance(value, Mapping):
            raise PayrollPaymentError(code, message)
        return value

    def _normalize_dispatch_result(self, instruction, request_payload, raw) -> dict:
        result = self._require_mapping(
            raw,
            code="PAYROLL_PAYMENT_PROVIDER_CONTRACT_INVALID",
            message="payment provider dispatch result must be an object",
        )
        expected = {
            "tenantId": int(instruction.tenant_id),
            "instructionId": str(instruction.id),
            "instructionNo": instruction.instruction_no,
            "providerCode": instruction.provider_code,
            "requestedAmount": str(_money(instruction.requested_amount)),
            "currencyCode": instruction.currency_code,
            "idempotencyKey": request_payload["idempotencyKey"],
            "status": "SENT",
        }
        if any(str(result.get(key)) != str(value) for key, value in expected.items()):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_CONTRACT_INVALID",
                "payment provider dispatch identity does not match the instruction",
            )
        dispatch_receipt_id = str(result.get("dispatchReceiptId") or "").strip()
        if not dispatch_receipt_id:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_CONTRACT_INVALID",
                "payment provider dispatchReceiptId is required",
            )
        return {**expected, "dispatchReceiptId": dispatch_receipt_id}

    @transaction.atomic
    def _complete_dispatch(self, instruction_id, lease_token: str, result: dict):
        instruction = self._lock_instruction(instruction_id)
        if instruction.status == PayrollPaymentInstruction.Status.SENT:
            persisted = (instruction.provider_receipt_json or {}).get("dispatch") or {}
            if persisted != result:
                raise PayrollPaymentError(
                    "PAYROLL_PAYMENT_DISPATCH_CONFLICT",
                    "payment instruction already has a different dispatch receipt",
                )
            return instruction
        if instruction.status != PayrollPaymentInstruction.Status.CREATED:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_INVALID_STATE", "payment instruction cannot be marked sent"
            )
        claim = (instruction.provider_receipt_json or {}).get("dispatchClaim") or {}
        if claim.get("leaseToken") != lease_token or claim.get("state") != "RUNNING":
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_DISPATCH_CLAIM_LOST",
                "payment dispatch claim is no longer owned by this worker",
            )
        instruction.status = PayrollPaymentInstruction.Status.SENT
        instruction.provider_receipt_json = {"dispatch": result}
        instruction.sent_at = timezone.now()
        instruction.updated_by = self.actor_user_id
        instruction.save(
            update_fields=[
                "status",
                "provider_receipt_json",
                "sent_at",
                "updated_by",
                "updated_at",
            ]
        )
        return instruction

    def dispatch(self, *, instruction_id) -> PayrollPaymentInstruction:
        instruction = PayrollPaymentInstruction.objects.filter(
            id=instruction_id, tenant_id=self.tenant_id
        ).first()
        if instruction is None:
            raise PayrollPaymentError("PAYROLL_PAYMENT_NOT_FOUND", "payment instruction not found")
        if instruction.status in {
            PayrollPaymentInstruction.Status.SENT,
            PayrollPaymentInstruction.Status.ACCEPTED,
            PayrollPaymentInstruction.Status.REJECTED,
        }:
            return instruction
        try:
            provider = PaymentProviderRegistry.resolve(instruction.provider_code)
        except PaymentProviderRegistryError as exc:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_UNAVAILABLE", str(exc)
            ) from exc

        claimed, request_payload, lease_token = self._claim_dispatch(instruction.id)
        if request_payload is None:
            return claimed
        try:
            raw_result = provider.dispatch(dict(request_payload))
        except Exception as exc:
            self._release_dispatch_claim(
                instruction.id, lease_token, error="trusted provider dispatch failed"
            )
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_UNAVAILABLE",
                "trusted payment provider dispatch failed",
            ) from exc
        try:
            result = self._normalize_dispatch_result(claimed, request_payload, raw_result)
        except PayrollPaymentError as exc:
            self._release_dispatch_claim(instruction.id, lease_token, error=str(exc))
            raise
        return self._complete_dispatch(instruction.id, lease_token, result)

    def _normalize_provider_receipt(self, instruction, raw) -> dict:
        receipt = self._require_mapping(
            raw,
            code="PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
            message="verified payment receipt must be an object",
        )
        status = str(receipt.get("status") or "").strip().upper()
        if status not in {
            PayrollPaymentInstruction.Status.ACCEPTED,
            PayrollPaymentInstruction.Status.REJECTED,
        }:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "verified payment receipt status must be ACCEPTED or REJECTED",
            )
        amount = _money(receipt.get("settledAmount"))
        expected = {
            "tenantId": int(instruction.tenant_id),
            "instructionId": str(instruction.id),
            "instructionNo": instruction.instruction_no,
            "providerCode": instruction.provider_code,
            "currencyCode": instruction.currency_code,
            "idempotencyKey": self._idempotency_key(instruction),
        }
        if any(str(receipt.get(key)) != str(value) for key, value in expected.items()):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "verified payment receipt identity does not match the instruction",
            )
        if status == PayrollPaymentInstruction.Status.ACCEPTED and amount != _money(
            instruction.requested_amount
        ):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "accepted payment amount must match the dispatched instruction",
            )
        if status == PayrollPaymentInstruction.Status.REJECTED and amount != Decimal("0.00"):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "rejected payment receipt cannot report a settled amount",
            )
        receipt_no = str(receipt.get("receiptNo") or "").strip()
        if not receipt_no:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "verified payment receipt number is required",
            )
        return {
            **expected,
            "receiptNo": receipt_no,
            "status": status,
            "settledAmount": str(amount),
        }

    @transaction.atomic
    def _apply_provider_receipt(self, instruction_id, receipt: dict):
        instruction = self._lock_instruction(instruction_id)
        target = receipt["status"]
        if instruction.status in {
            PayrollPaymentInstruction.Status.ACCEPTED,
            PayrollPaymentInstruction.Status.REJECTED,
        }:
            persisted = (instruction.provider_receipt_json or {}).get("receipt") or {}
            comparable = {
                key: persisted.get(key)
                for key in receipt
            }
            if instruction.status != target or comparable != receipt:
                raise PayrollPaymentError(
                    "PAYROLL_PAYMENT_RECEIPT_CONFLICT",
                    "payment already has a different terminal provider receipt",
                )
            return instruction
        if instruction.status != PayrollPaymentInstruction.Status.SENT:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_INVALID_STATE",
                "only a provider-dispatched instruction can receive a trusted receipt",
            )
        dispatch = (instruction.provider_receipt_json or {}).get("dispatch")
        if not isinstance(dispatch, Mapping):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "payment dispatch evidence is missing",
            )
        received_at = timezone.now()
        instruction.status = target
        instruction.provider_receipt_json = {
            "dispatch": dict(dispatch),
            "receipt": {**receipt, "receivedAt": received_at.isoformat()},
        }
        instruction.received_at = received_at
        instruction.updated_by = self.actor_user_id
        instruction.save(
            update_fields=[
                "status",
                "provider_receipt_json",
                "received_at",
                "updated_by",
                "updated_at",
            ]
        )
        if target == PayrollPaymentInstruction.Status.ACCEPTED:
            emit_registered_event(
                tenant_id=self.tenant_id,
                event_name=EVENT_PAYMENT_ACCEPTED,
                payload={
                    "paymentInstructionId": str(instruction.id),
                    "payrollResultId": str(instruction.payroll_result_id),
                    "receiptNo": receipt["receiptNo"],
                    "requestedAmount": str(instruction.requested_amount),
                    "settledAmount": receipt["settledAmount"],
                    "currencyCode": instruction.currency_code,
                    "receivedAt": received_at.isoformat(),
                },
                correlation_id=self.correlation_id,
            )
        return instruction

    def ingest_provider_receipt(
        self, *, instruction_id, provider_payload: Mapping
    ) -> PayrollPaymentInstruction:
        instruction = PayrollPaymentInstruction.objects.filter(
            id=instruction_id, tenant_id=self.tenant_id
        ).first()
        if instruction is None:
            raise PayrollPaymentError("PAYROLL_PAYMENT_NOT_FOUND", "payment instruction not found")
        try:
            provider = PaymentProviderRegistry.resolve(instruction.provider_code)
        except PaymentProviderRegistryError as exc:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_UNAVAILABLE", str(exc)
            ) from exc
        try:
            verified = provider.verify_receipt(provider_payload)
        except Exception as exc:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_PROVIDER_RECEIPT_INVALID",
                "payment provider could not authenticate the receipt",
            ) from exc
        receipt = self._normalize_provider_receipt(instruction, verified)
        return self._apply_provider_receipt(instruction.id, receipt)

    def mark_sent(self, *, instruction_id) -> PayrollPaymentInstruction:
        del instruction_id
        raise PayrollPaymentError(
            "PAYROLL_PAYMENT_TRUSTED_PROVIDER_REQUIRED",
            "payment state can only advance through a configured trusted provider",
        )

    def record_receipt(self, **kwargs) -> PayrollPaymentInstruction:
        del kwargs
        raise PayrollPaymentError(
            "PAYROLL_PAYMENT_TRUSTED_RECEIPT_REQUIRED",
            "payment receipt can only be ingested by a trusted provider worker",
        )

    @staticmethod
    def _trusted_terminal_receipt(instruction: PayrollPaymentInstruction) -> Mapping:
        evidence = instruction.provider_receipt_json or {}
        dispatch = evidence.get("dispatch") if isinstance(evidence, Mapping) else None
        receipt = evidence.get("receipt") if isinstance(evidence, Mapping) else None
        if not isinstance(dispatch, Mapping) or not isinstance(receipt, Mapping):
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_TRUSTED_RECEIPT_REQUIRED",
                "payment terminal evidence was not produced by the trusted provider boundary",
            )
        return receipt

    @transaction.atomic
    def publish_payslip(
        self, *, result_id, payslip_no: str
    ) -> PayrollPayslipFact:
        payslip_no = str(payslip_no or "").strip()
        if not payslip_no:
            raise PayrollPaymentError(
                "PAYROLL_PAYSLIP_REFERENCE_REQUIRED", "payslip number is required"
            )
        result = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise PayrollPaymentError("PAYROLL_RESULT_NOT_FOUND", "payroll result not found")
        try:
            verify_payroll_result_input_evidence(result)
        except PayrollCalculationError as exc:
            raise PayrollPaymentError(exc.code, str(exc)) from exc
        instruction = PayrollPaymentInstruction.objects.filter(
            tenant_id=self.tenant_id,
            payroll_result_id=result.id,
            status=PayrollPaymentInstruction.Status.ACCEPTED,
        ).first()
        if instruction is None:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_ACCEPTED",
                "payslip publication requires an accepted payment receipt",
            )
        existing = PayrollPayslipFact.objects.filter(
            tenant_id=self.tenant_id, payroll_result_id=result.id
        ).first()
        if existing:
            if existing.payslip_no != payslip_no:
                raise PayrollPaymentError(
                    "PAYROLL_PAYSLIP_IDEMPOTENCY_CONFLICT",
                    "result already has another payslip number",
                )
            return existing
        line_rows = list(
            PayrollCalculationLine.objects.filter(
                tenant_id=self.tenant_id, payroll_result_id=result.id
            )
            .order_by("sequence_no")
            .values("item_code", "item_name", "item_type", "amount", "currency_code")
        )
        lines = [
            {
                "itemCode": row["item_code"],
                "itemName": row["item_name"],
                "itemType": row["item_type"],
                "amount": str(row["amount"]),
                "currencyCode": row["currency_code"],
            }
            for row in line_rows
        ]
        receipt = self._trusted_terminal_receipt(instruction)
        statement = {
            "resultId": str(result.id),
            "staffId": str(result.staff_id),
            "periodId": str(result.payroll_period_id),
            "currencyCode": result.currency_code,
            "grossAmount": str(result.gross_amount),
            "deductionAmount": str(result.deduction_amount),
            "netAmount": str(result.net_amount),
            "paymentReceiptNo": receipt["receiptNo"],
            "lines": lines,
        }
        payslip = PayrollPayslipFact.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            payslip_no=payslip_no,
            payroll_result_id=result.id,
            payment_instruction_id=instruction.id,
            staff_id=result.staff_id,
            content_hash=_hash(statement),
            statement_json=statement,
            published_at=timezone.now(),
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_PAYSLIP_PUBLISHED,
            payload={
                "payslipId": str(payslip.id),
                "payrollResultId": str(result.id),
                "staffId": str(result.staff_id),
                "contentHash": payslip.content_hash,
                "publishedAt": payslip.published_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return payslip

    @transaction.atomic
    def reconcile(
        self, *, instruction_id, reconciliation_no: str
    ) -> PayrollFinanceReconciliationFact:
        reconciliation_no = str(reconciliation_no or "").strip()
        if not reconciliation_no:
            raise PayrollPaymentError(
                "PAYROLL_RECONCILIATION_REFERENCE_REQUIRED",
                "reconciliation number is required",
            )
        if not self.actor_user_id:
            raise PayrollPaymentError(
                "PAYROLL_RECONCILIATION_ACTOR_REQUIRED", "reconciliation actor is required"
            )
        instruction = self._lock_instruction(instruction_id)
        if instruction.status != PayrollPaymentInstruction.Status.ACCEPTED:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_ACCEPTED",
                "finance reconciliation requires an accepted receipt",
            )
        existing = PayrollFinanceReconciliationFact.objects.filter(
            tenant_id=self.tenant_id, payment_instruction_id=instruction.id
        ).first()
        if existing:
            if existing.reconciliation_no != reconciliation_no:
                raise PayrollPaymentError(
                    "PAYROLL_RECONCILIATION_IDEMPOTENCY_CONFLICT",
                    "payment already has another reconciliation fact",
                )
            return existing
        receipt = self._trusted_terminal_receipt(instruction)
        settled = _money(receipt.get("settledAmount"))
        expected = _money(instruction.requested_amount)
        difference = settled - expected
        status = (
            PayrollFinanceReconciliationFact.Status.MATCHED
            if difference == 0
            else PayrollFinanceReconciliationFact.Status.MISMATCH
        )
        fact = PayrollFinanceReconciliationFact.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            reconciliation_no=reconciliation_no,
            payment_instruction_id=instruction.id,
            expected_amount=expected,
            settled_amount=settled,
            difference_amount=difference,
            currency_code=instruction.currency_code,
            status=status,
            receipt_snapshot_json=dict(instruction.provider_receipt_json),
            reconciled_by=self.actor_user_id,
            reconciled_at=timezone.now(),
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_FINANCE_RECONCILED,
            payload={
                "reconciliationId": str(fact.id),
                "paymentInstructionId": str(instruction.id),
                "status": fact.status,
                "expectedAmount": str(fact.expected_amount),
                "settledAmount": str(fact.settled_amount),
                "differenceAmount": str(fact.difference_amount),
                "currencyCode": fact.currency_code,
                "reconciledAt": fact.reconciled_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return fact

    def _lock_instruction(self, instruction_id) -> PayrollPaymentInstruction:
        instruction = (
            PayrollPaymentInstruction.objects.select_for_update()
            .filter(id=instruction_id, tenant_id=self.tenant_id)
            .first()
        )
        if instruction is None:
            raise PayrollPaymentError(
                "PAYROLL_PAYMENT_NOT_FOUND", "payment instruction not found"
            )
        return instruction
