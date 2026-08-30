"""Fail-closed HR15 takeover of the legacy payroll and payslip assets."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, TypeVar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_LEGACY_CUTOVER_ACTIVATED,
    EVENT_LEGACY_INVENTORY_CAPTURED,
)
from hr_payroll.calculation_models import (
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollPayslipFact,
)
from hr_payroll.legacy_takeover_models import (
    LegacyPayrollAssetInventory,
    LegacyPayrollCutoverControl,
    LegacyPayrollMappingFact,
    LegacyPayrollWriteBlockAudit,
)
from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.legacy_reconciliation_service import _money


T = TypeVar("T")
_LEGACY_TERMINAL = frozenset({"confirmed", "paid"})
security_logger = logging.getLogger("security.hr15_legacy_write_block")


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


class LegacyPayrollTakeoverError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LegacyPayrollInventoryOutcome:
    inventory: LegacyPayrollAssetInventory
    created: bool


class LegacyPayrollTakeoverService:
    """Inventory, reconcile and activate one tenant's read-only cutover."""

    def __init__(
        self,
        tenant_id: int,
        *,
        actor_user_id: int | None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise LegacyPayrollTakeoverError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def _legacy_rows(self, *, lock: bool) -> list[dict]:
        from payroll.models.models import Payslip

        rows = Payslip.objects.entire().filter(
            employee_id__employee_work_info__company_id=self.tenant_id
        )
        if lock:
            rows = rows.select_for_update()
        return list(
            rows.order_by("id").values(
                "id",
                "employee_id_id",
                "start_date",
                "end_date",
                "gross_pay",
                "deduction",
                "net_pay",
                "status",
            )
        )

    def _staff_map(self, employee_ids: set[int]) -> dict[int, object]:
        if not employee_ids:
            return {}
        from hr_staff.models import HrStaffMaster

        return dict(
            HrStaffMaster.objects.filter(
                tenant_id=self.tenant_id,
                legacy_employee_id__in=employee_ids,
            ).values_list("legacy_employee_id", "id")
        )

    def _period_map(self, ranges: set[tuple]) -> dict[tuple, object]:
        if not ranges:
            return {}
        rows = PayrollPeriod.objects.filter(
            tenant_id=self.tenant_id,
            start_date__in={item[0] for item in ranges},
            end_date__in={item[1] for item in ranges},
        ).values("id", "start_date", "end_date")
        return {
            (row["start_date"], row["end_date"]): row["id"]
            for row in rows
            if (row["start_date"], row["end_date"]) in ranges
        }

    def _result_map(self, period_ids: set[object]) -> dict[tuple, list[dict]]:
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        if not period_ids:
            return grouped
        rows = PayrollResultFact.objects.filter(
            tenant_id=self.tenant_id, payroll_period_id__in=period_ids
        ).values(
            "id",
            "payroll_period_id",
            "staff_id",
            "gross_amount",
            "deduction_amount",
            "net_amount",
            "currency_code",
            "status",
            "supersedes_result_id",
        )
        for row in rows:
            grouped[(row["payroll_period_id"], row["staff_id"])].append(row)
        return grouped

    def _payslip_map(self, result_ids: set[object]) -> dict[object, dict]:
        if not result_ids:
            return {}
        return {
            row["payroll_result_id"]: row
            for row in PayrollPayslipFact.objects.filter(
                tenant_id=self.tenant_id, payroll_result_id__in=result_ids
            ).values(
                "id", "payroll_result_id", "payment_instruction_id", "content_hash"
            )
        }

    def _payment_map(self, payment_ids: set[object]) -> dict[object, dict]:
        if not payment_ids:
            return {}
        return {
            row["id"]: row
            for row in PayrollPaymentInstruction.objects.filter(
                tenant_id=self.tenant_id, id__in=payment_ids
            ).values("id", "status", "requested_amount", "provider_receipt_json")
        }

    def _finance_map(self, payment_ids: set[object]) -> dict[object, dict]:
        if not payment_ids:
            return {}
        return {
            row["payment_instruction_id"]: row
            for row in PayrollFinanceReconciliationFact.objects.filter(
                tenant_id=self.tenant_id, payment_instruction_id__in=payment_ids
            ).values(
                "id",
                "payment_instruction_id",
                "status",
                "expected_amount",
                "settled_amount",
                "difference_amount",
            )
        }

    @staticmethod
    def _single_final_result(rows: list[dict]) -> tuple[str, dict | None]:
        terminal = [
            row
            for row in rows
            if row["status"]
            in {
                PayrollResultFact.Status.FINALIZED,
                PayrollResultFact.Status.ADJUSTED,
                PayrollResultFact.Status.REVERSED,
            }
        ]
        if not terminal:
            return "AUTHORITY_RESULT_MISSING", None
        # A legacy row cannot safely flatten an append-only adjustment/reversal
        # chain into one amount. Such periods require an explicit migration
        # evidence strategy rather than an automatic pass.
        if len(terminal) != 1 or terminal[0]["status"] != PayrollResultFact.Status.FINALIZED:
            return "AUTHORITY_RESULT_CHAIN_UNAVAILABLE", None
        return "MATCHED", terminal[0]

    def _build_snapshot(self, *, lock_legacy: bool) -> dict:
        legacy_rows = self._legacy_rows(lock=lock_legacy)
        employee_ids = {int(row["employee_id_id"]) for row in legacy_rows}
        staff_map = self._staff_map(employee_ids)
        ranges = {(row["start_date"], row["end_date"]) for row in legacy_rows}
        period_map = self._period_map(ranges)
        result_map = self._result_map(set(period_map.values()))
        result_ids = {
            row["id"] for rows in result_map.values() for row in rows
        }
        payslip_map = self._payslip_map(result_ids)
        payment_ids = {row["payment_instruction_id"] for row in payslip_map.values()}
        payment_map = self._payment_map(payment_ids)
        finance_map = self._finance_map(payment_ids)

        mappings: list[dict] = []
        reason_codes: set[str] = set()
        for legacy in legacy_rows:
            employee_id = int(legacy["employee_id_id"])
            status = str(legacy.get("status") or "").lower()
            legacy_amounts = (
                _money(legacy.get("gross_pay")),
                _money(legacy.get("deduction")),
                _money(legacy.get("net_pay")),
            )
            legacy_amount_hash = _hash([str(value) for value in legacy_amounts])
            mapping = {
                "legacy_payslip_id": int(legacy["id"]),
                "legacy_employee_ref_hash": _hash(
                    {"tenant": self.tenant_id, "legacyEmployeeId": employee_id}
                ),
                "staff_id": None,
                "payroll_period_id": None,
                "payroll_result_id": None,
                "payroll_payslip_id": None,
                "finance_reconciliation_id": None,
                "reconciliation_status": "LEGACY_NON_FINAL",
                "legacy_amount_hash": legacy_amount_hash,
                "authority_amount_hash": "",
            }
            authority_evidence = {}

            if status not in _LEGACY_TERMINAL:
                reason_codes.add("LEGACY_NON_FINAL")
            else:
                staff_id = staff_map.get(employee_id)
                if staff_id is None:
                    mapping["reconciliation_status"] = "UNMAPPED_STAFF"
                    reason_codes.add("UNMAPPED_STAFF")
                else:
                    mapping["staff_id"] = staff_id
                    period_id = period_map.get((legacy["start_date"], legacy["end_date"]))
                    if period_id is None:
                        mapping["reconciliation_status"] = "AUTHORITY_PERIOD_MISSING"
                        reason_codes.add("AUTHORITY_PERIOD_MISSING")
                    else:
                        mapping["payroll_period_id"] = period_id
                        state, result = self._single_final_result(
                            result_map.get((period_id, staff_id), [])
                        )
                        if result is None:
                            mapping["reconciliation_status"] = state
                            reason_codes.add(state)
                        else:
                            mapping["payroll_result_id"] = result["id"]
                            authority_amounts = (
                                _money(result["gross_amount"]),
                                _money(result["deduction_amount"]),
                                _money(result["net_amount"]),
                            )
                            mapping["authority_amount_hash"] = _hash(
                                [str(value) for value in authority_amounts]
                            )
                            if authority_amounts != legacy_amounts:
                                mapping["reconciliation_status"] = "AMOUNT_MISMATCH"
                                reason_codes.add("AMOUNT_MISMATCH")
                            else:
                                payslip = payslip_map.get(result["id"])
                                if payslip is None:
                                    mapping["reconciliation_status"] = "AUTHORITY_PAYSLIP_MISSING"
                                    reason_codes.add("AUTHORITY_PAYSLIP_MISSING")
                                else:
                                    mapping["payroll_payslip_id"] = payslip["id"]
                                    authority_evidence["payslipContentHash"] = payslip[
                                        "content_hash"
                                    ]
                                    payment = payment_map.get(payslip["payment_instruction_id"])
                                    payment_evidence = (
                                        payment.get("provider_receipt_json")
                                        if payment is not None
                                        else None
                                    )
                                    trusted_receipt = (
                                        isinstance(payment_evidence, dict)
                                        and isinstance(payment_evidence.get("dispatch"), dict)
                                        and isinstance(payment_evidence.get("receipt"), dict)
                                    )
                                    if (
                                        payment is None
                                        or payment["status"]
                                        != PayrollPaymentInstruction.Status.ACCEPTED
                                        or not trusted_receipt
                                    ):
                                        mapping["reconciliation_status"] = "PAYMENT_RECEIPT_UNAVAILABLE"
                                        reason_codes.add("PAYMENT_RECEIPT_UNAVAILABLE")
                                    else:
                                        authority_evidence["paymentReceiptHash"] = _hash(
                                            payment["provider_receipt_json"]
                                        )
                                        finance = finance_map.get(
                                            payslip["payment_instruction_id"]
                                        )
                                        if (
                                            finance is None
                                            or finance["status"]
                                            != PayrollFinanceReconciliationFact.Status.MATCHED
                                            or Decimal(finance["difference_amount"]) != 0
                                        ):
                                            mapping["reconciliation_status"] = "FINANCE_EVIDENCE_UNAVAILABLE"
                                            reason_codes.add("FINANCE_EVIDENCE_UNAVAILABLE")
                                        else:
                                            mapping["finance_reconciliation_id"] = finance["id"]
                                            mapping["reconciliation_status"] = "MATCHED"
                                            authority_evidence["financeEvidenceHash"] = _hash(
                                                {
                                                    "status": finance["status"],
                                                    "expected": finance["expected_amount"],
                                                    "settled": finance["settled_amount"],
                                                    "difference": finance["difference_amount"],
                                                }
                                            )

            mapping["evidence_hash"] = _hash(
                {"mapping": mapping, "authorityEvidence": authority_evidence}
            )
            mappings.append(mapping)

        if not legacy_rows:
            reason_codes.add("LEGACY_HISTORY_EVIDENCE_MISSING")
        matched_count = sum(
            item["reconciliation_status"] == "MATCHED" for item in mappings
        )
        snapshot_hash = _hash(
            {
                "tenant": self.tenant_id,
                "source": "payroll.Payslip",
                "mappingEvidence": [item["evidence_hash"] for item in mappings],
            }
        )
        return {
            "mappings": mappings,
            "legacyRowCount": len(mappings),
            "matchedRowCount": matched_count,
            "unavailableRowCount": len(mappings) - matched_count,
            "reasonCodes": sorted(reason_codes),
            "snapshotHash": snapshot_hash,
            "status": (
                LegacyPayrollAssetInventory.Status.COMPLETE
                if mappings and not reason_codes and matched_count == len(mappings)
                else LegacyPayrollAssetInventory.Status.UNAVAILABLE
            ),
        }

    @transaction.atomic
    def capture_inventory(self, *, inventory_no: str) -> LegacyPayrollInventoryOutcome:
        inventory_no = str(inventory_no or "").strip()
        if not inventory_no:
            raise LegacyPayrollTakeoverError(
                "LEGACY_INVENTORY_NO_REQUIRED", "inventoryNo is required"
            )
        if len(inventory_no) > 96:
            raise LegacyPayrollTakeoverError(
                "LEGACY_INVENTORY_NO_INVALID", "inventoryNo exceeds 96 characters"
            )
        if not self.actor_user_id:
            raise LegacyPayrollTakeoverError(
                "LEGACY_TAKEOVER_ACTOR_REQUIRED", "an authenticated actor is required"
            )
        control, _ = LegacyPayrollCutoverControl.objects.select_for_update().get_or_create(
            tenant_id=self.tenant_id,
            defaults={"created_by": self.actor_user_id, "updated_by": self.actor_user_id},
        )
        if control.status == LegacyPayrollCutoverControl.Status.ACTIVE:
            raise LegacyPayrollTakeoverError(
                "LEGACY_TAKEOVER_ALREADY_ACTIVE", "active cutover evidence is immutable"
            )
        existing = LegacyPayrollAssetInventory.objects.filter(
            tenant_id=self.tenant_id, inventory_no=inventory_no
        ).first()
        if existing is not None:
            return LegacyPayrollInventoryOutcome(existing, False)

        snapshot = self._build_snapshot(lock_legacy=True)
        now = timezone.now()
        inventory = LegacyPayrollAssetInventory.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            inventory_no=inventory_no,
            status=snapshot["status"],
            legacy_row_count=snapshot["legacyRowCount"],
            matched_row_count=snapshot["matchedRowCount"],
            unavailable_row_count=snapshot["unavailableRowCount"],
            snapshot_hash=snapshot["snapshotHash"],
            reason_codes_json=snapshot["reasonCodes"],
            captured_at=now,
        )
        LegacyPayrollMappingFact.objects.bulk_create(
            [
                LegacyPayrollMappingFact(
                    tenant_id=self.tenant_id,
                    created_by=self.actor_user_id,
                    updated_by=self.actor_user_id,
                    inventory_id=inventory.id,
                    **mapping,
                )
                for mapping in snapshot["mappings"]
            ]
        )
        control.latest_inventory_id = inventory.id
        control.latest_snapshot_hash = inventory.snapshot_hash
        control.status = (
            LegacyPayrollCutoverControl.Status.VERIFIED
            if inventory.status == LegacyPayrollAssetInventory.Status.COMPLETE
            else LegacyPayrollCutoverControl.Status.UNAVAILABLE
        )
        control.verified_at = now if inventory.status == LegacyPayrollAssetInventory.Status.COMPLETE else None
        control.updated_by = self.actor_user_id
        control.save(
            update_fields=[
                "latest_inventory_id",
                "latest_snapshot_hash",
                "status",
                "verified_at",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_LEGACY_INVENTORY_CAPTURED,
            payload={
                "inventoryId": str(inventory.id),
                "inventoryNo": inventory.inventory_no,
                "status": inventory.status,
                "legacyRowCount": inventory.legacy_row_count,
                "matchedRowCount": inventory.matched_row_count,
                "snapshotHash": inventory.snapshot_hash,
                "reasonCodes": inventory.reason_codes_json,
            },
            correlation_id=self.correlation_id,
        )
        return LegacyPayrollInventoryOutcome(inventory, True)

    @transaction.atomic
    def activate(
        self,
        *,
        inventory_id,
        activation_key: str,
        evidence: dict | None,
    ) -> LegacyPayrollCutoverControl:
        activation_key = str(activation_key or "").strip()
        if not activation_key:
            raise LegacyPayrollTakeoverError(
                "LEGACY_ACTIVATION_KEY_REQUIRED", "activationKey is required"
            )
        if len(activation_key) > 96:
            raise LegacyPayrollTakeoverError(
                "LEGACY_ACTIVATION_KEY_INVALID", "activationKey exceeds 96 characters"
            )
        try:
            inventory_id = uuid.UUID(str(inventory_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise LegacyPayrollTakeoverError(
                "LEGACY_INVENTORY_ID_INVALID", "inventoryId must be a UUID"
            ) from exc
        if not self.actor_user_id:
            raise LegacyPayrollTakeoverError(
                "LEGACY_TAKEOVER_ACTOR_REQUIRED", "an authenticated actor is required"
            )
        evidence = evidence if isinstance(evidence, dict) else {}
        required = ("approvalTicket", "rollbackPlanRef")
        missing = [field for field in required if not str(evidence.get(field) or "").strip()]
        if missing:
            raise LegacyPayrollTakeoverError(
                "LEGACY_CUTOVER_EVIDENCE_UNAVAILABLE",
                "approvalTicket and rollbackPlanRef are required",
            )
        safe_evidence = {field: str(evidence[field]).strip() for field in required}
        evidence_hash = _hash(safe_evidence)

        control = LegacyPayrollCutoverControl.objects.select_for_update().filter(
            tenant_id=self.tenant_id
        ).first()
        if control is None:
            raise LegacyPayrollTakeoverError(
                "LEGACY_INVENTORY_NOT_FOUND", "capture an inventory before activation"
            )
        if control.status == LegacyPayrollCutoverControl.Status.ACTIVE:
            if (
                control.activation_key == activation_key
                and control.latest_inventory_id == inventory_id
                and control.activation_evidence_hash == evidence_hash
            ):
                return control
            raise LegacyPayrollTakeoverError(
                "LEGACY_ACTIVATION_IDEMPOTENCY_CONFLICT",
                "cutover is already active with different evidence",
            )
        inventory = LegacyPayrollAssetInventory.objects.filter(
            id=inventory_id, tenant_id=self.tenant_id
        ).first()
        if inventory is None:
            raise LegacyPayrollTakeoverError(
                "LEGACY_INVENTORY_NOT_FOUND", "inventory not found inside tenant"
            )
        if (
            inventory.id != control.latest_inventory_id
            or inventory.status != LegacyPayrollAssetInventory.Status.COMPLETE
        ):
            raise LegacyPayrollTakeoverError(
                "LEGACY_TAKEOVER_UNAVAILABLE",
                "latest inventory is incomplete; missing history cannot be approved",
            )

        current = self._build_snapshot(lock_legacy=True)
        if (
            current["status"] != LegacyPayrollAssetInventory.Status.COMPLETE
            or current["snapshotHash"] != inventory.snapshot_hash
        ):
            raise LegacyPayrollTakeoverError(
                "LEGACY_CUTOVER_EVIDENCE_STALE",
                "legacy or HR15 facts changed after inventory; capture a new inventory",
            )

        now = timezone.now()
        control.status = LegacyPayrollCutoverControl.Status.ACTIVE
        control.activation_key = activation_key
        control.activation_evidence_hash = evidence_hash
        control.activation_evidence_json = safe_evidence
        control.write_block_enabled = True
        control.activated_at = now
        control.activated_by = self.actor_user_id
        control.updated_by = self.actor_user_id
        control.save(
            update_fields=[
                "status",
                "activation_key",
                "activation_evidence_hash",
                "activation_evidence_json",
                "write_block_enabled",
                "activated_at",
                "activated_by",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_LEGACY_CUTOVER_ACTIVATED,
            payload={
                "cutoverId": str(control.id),
                "inventoryId": str(inventory.id),
                "snapshotHash": inventory.snapshot_hash,
                "activationEvidenceHash": evidence_hash,
                "writeBlockEnabled": True,
                "activatedAt": now.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return control


def execute_guarded_legacy_payslip_write(
    *,
    tenant_ids: set[int],
    operation: str,
    object_refs: list[object],
    write: Callable[[], T],
) -> T:
    """Serialize legacy writes with cutover activation and audit denials."""

    normalized = {int(value) for value in tenant_ids if value}
    if not normalized:
        raise ValidationError(
            "LEGACY_PAYROLL_TENANT_UNAVAILABLE: a concrete tenant is required"
        )
    blocked = []
    with transaction.atomic():
        controls = list(
            LegacyPayrollCutoverControl.objects.select_for_update().filter(
                tenant_id__in=normalized,
                status=LegacyPayrollCutoverControl.Status.ACTIVE,
                write_block_enabled=True,
            )
        )
        if not controls:
            return write()

        try:
            from horilla.horilla_middlewares import _thread_locals

            request = getattr(_thread_locals, "request", None)
            actor_id = getattr(getattr(request, "user", None), "id", None)
        except Exception:  # pragma: no cover - audit metadata is best effort
            actor_id = None
        ref_hash = _hash([str(value) for value in sorted(object_refs, key=str)])
        now = timezone.now()
        LegacyPayrollWriteBlockAudit.objects.bulk_create(
            [
                LegacyPayrollWriteBlockAudit(
                    tenant_id=control.tenant_id,
                    cutover_id=control.id,
                    operation=str(operation or "WRITE")[:24],
                    object_ref_hash=ref_hash,
                    actor_user_id=actor_id,
                    reason_code="LEGACY_PAYROLL_FORMAL_WRITE_BLOCKED",
                    blocked_at=now,
                )
                for control in controls
            ]
        )
        blocked = [control.tenant_id for control in controls]
    security_logger.warning(
        "legacy_payroll_formal_write_blocked tenants=%s operation=%s object_ref_hash=%s",
        ",".join(str(value) for value in sorted(blocked)),
        operation,
        ref_hash,
    )
    # In normal autocommit requests the database audit is committed before the
    # exception. The structured security log is also emitted so an enclosing
    # caller transaction cannot erase the only trace of a denied attempt.
    raise ValidationError(
        "LEGACY_PAYROLL_FORMAL_WRITE_BLOCKED: HR15 is authoritative for tenant(s) "
        + ",".join(str(value) for value in sorted(blocked))
    )
