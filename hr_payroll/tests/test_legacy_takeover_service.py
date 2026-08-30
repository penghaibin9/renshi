import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from hr_payroll.calculation_models import (
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
)
from hr_payroll.models import PayrollResultFact
from hr_payroll.legacy_takeover_models import (
    LegacyPayrollCutoverControl,
    LegacyPayrollWriteBlockAudit,
)
from hr_payroll.services.legacy_takeover_service import (
    LegacyPayrollTakeoverService,
    execute_guarded_legacy_payslip_write,
)


class StubTakeoverService(LegacyPayrollTakeoverService):
    def __init__(
        self,
        *,
        legacy_rows,
        staff_map=None,
        period_map=None,
        result_map=None,
        payslip_map=None,
        payment_map=None,
        finance_map=None,
    ):
        super().__init__(7, actor_user_id=9)
        self.rows = legacy_rows
        self.staff = staff_map or {}
        self.periods = period_map or {}
        self.results = result_map or {}
        self.payslips = payslip_map or {}
        self.payments = payment_map or {}
        self.finance = finance_map or {}

    def _legacy_rows(self, *, lock):
        return self.rows

    def _staff_map(self, employee_ids):
        return self.staff

    def _period_map(self, ranges):
        return self.periods

    def _result_map(self, period_ids):
        return self.results

    def _payslip_map(self, result_ids):
        return self.payslips

    def _payment_map(self, payment_ids):
        return self.payments

    def _finance_map(self, payment_ids):
        return self.finance


class LegacyPayrollTakeoverSnapshotTests(SimpleTestCase):
    def _legacy(self):
        return {
            "id": 41,
            "employee_id_id": 18,
            "start_date": "2026-07-01",
            "end_date": "2026-08-01",
            "gross_pay": 1000.10,
            "deduction": 100.10,
            "net_pay": 900,
            "status": "paid",
        }

    def _complete_service(self):
        staff_id = uuid.uuid4()
        period_id = uuid.uuid4()
        result_id = uuid.uuid4()
        payslip_id = uuid.uuid4()
        payment_id = uuid.uuid4()
        finance_id = uuid.uuid4()
        return StubTakeoverService(
            legacy_rows=[self._legacy()],
            staff_map={18: staff_id},
            period_map={("2026-07-01", "2026-08-01"): period_id},
            result_map={
                (period_id, staff_id): [
                    {
                        "id": result_id,
                        "payroll_period_id": period_id,
                        "staff_id": staff_id,
                        "gross_amount": Decimal("1000.10"),
                        "deduction_amount": Decimal("100.10"),
                        "net_amount": Decimal("900.00"),
                        "currency_code": "CNY",
                        "status": PayrollResultFact.Status.FINALIZED,
                        "supersedes_result_id": None,
                    }
                ]
            },
            payslip_map={
                result_id: {
                    "id": payslip_id,
                    "payroll_result_id": result_id,
                    "payment_instruction_id": payment_id,
                    "content_hash": "a" * 64,
                }
            },
            payment_map={
                payment_id: {
                    "id": payment_id,
                    "status": PayrollPaymentInstruction.Status.ACCEPTED,
                    "requested_amount": Decimal("900.00"),
                    "provider_receipt_json": {"receiptNo": "R-1"},
                }
            },
            finance_map={
                payment_id: {
                    "id": finance_id,
                    "payment_instruction_id": payment_id,
                    "status": PayrollFinanceReconciliationFact.Status.MATCHED,
                    "expected_amount": Decimal("900.00"),
                    "settled_amount": Decimal("900.00"),
                    "difference_amount": Decimal("0.00"),
                }
            },
        )

    def test_complete_snapshot_requires_result_payslip_payment_and_finance_chain(self):
        snapshot = self._complete_service()._build_snapshot(lock_legacy=True)

        self.assertEqual(snapshot["status"], "COMPLETE")
        self.assertEqual(snapshot["matchedRowCount"], 1)
        mapping = snapshot["mappings"][0]
        self.assertEqual(mapping["reconciliation_status"], "MATCHED")
        self.assertEqual(len(mapping["legacy_amount_hash"]), 64)
        self.assertNotIn("gross_amount", mapping)
        self.assertNotIn("net_pay", mapping)

    def test_missing_finance_evidence_is_unavailable_not_fabricated(self):
        service = self._complete_service()
        service.finance = {}

        snapshot = service._build_snapshot(lock_legacy=True)

        self.assertEqual(snapshot["status"], "UNAVAILABLE")
        self.assertIn("FINANCE_EVIDENCE_UNAVAILABLE", snapshot["reasonCodes"])
        self.assertEqual(
            snapshot["mappings"][0]["reconciliation_status"],
            "FINANCE_EVIDENCE_UNAVAILABLE",
        )

    def test_empty_legacy_history_is_unavailable(self):
        snapshot = StubTakeoverService(legacy_rows=[])._build_snapshot(
            lock_legacy=True
        )

        self.assertEqual(snapshot["status"], "UNAVAILABLE")
        self.assertIn("LEGACY_HISTORY_EVIDENCE_MISSING", snapshot["reasonCodes"])

    def test_adjustment_chain_never_becomes_a_false_one_row_match(self):
        service = self._complete_service()
        key = next(iter(service.results))
        base = service.results[key][0]
        service.results[key].append(
            {
                **base,
                "id": uuid.uuid4(),
                "status": PayrollResultFact.Status.ADJUSTED,
                "gross_amount": Decimal("10.00"),
                "deduction_amount": Decimal("0.00"),
                "net_amount": Decimal("10.00"),
                "supersedes_result_id": base["id"],
            }
        )

        snapshot = service._build_snapshot(lock_legacy=True)

        self.assertEqual(snapshot["status"], "UNAVAILABLE")
        self.assertIn("AUTHORITY_RESULT_CHAIN_UNAVAILABLE", snapshot["reasonCodes"])

    def test_snapshot_hash_changes_when_reconciled_assets_change(self):
        service = self._complete_service()
        first = service._build_snapshot(lock_legacy=True)["snapshotHash"]
        service.rows[0]["net_pay"] = 899
        second = service._build_snapshot(lock_legacy=True)["snapshotHash"]

        self.assertNotEqual(first, second)


class LegacyPayrollWriteBlockTests(SimpleTestCase):
    @patch("hr_payroll.services.legacy_takeover_service.transaction.atomic")
    def test_active_cutover_audits_and_blocks_write(self, atomic):
        atomic.return_value = nullcontext()
        control = SimpleNamespace(id=uuid.uuid4(), tenant_id=7)
        locked = Mock()
        locked.filter.return_value = [control]
        write = Mock()
        with patch.object(
            LegacyPayrollCutoverControl.objects,
            "select_for_update",
            return_value=locked,
        ), patch.object(
            LegacyPayrollWriteBlockAudit.objects, "bulk_create"
        ) as audit:
            with self.assertRaisesRegex(
                ValidationError, "LEGACY_PAYROLL_FORMAL_WRITE_BLOCKED"
            ):
                execute_guarded_legacy_payslip_write(
                    tenant_ids={7},
                    operation="UPDATE",
                    object_refs=[41],
                    write=write,
                )

        write.assert_not_called()
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0][0].tenant_id, 7)
        self.assertEqual(audit.call_args.args[0][0].operation, "UPDATE")

    @patch("hr_payroll.services.legacy_takeover_service.transaction.atomic")
    def test_non_active_tenant_can_still_write_during_reconciliation(self, atomic):
        atomic.return_value = nullcontext()
        locked = Mock()
        locked.filter.return_value = []
        write = Mock(return_value=3)
        with patch.object(
            LegacyPayrollCutoverControl.objects,
            "select_for_update",
            return_value=locked,
        ):
            result = execute_guarded_legacy_payslip_write(
                tenant_ids={7},
                operation="UPDATE",
                object_refs=[41],
                write=write,
            )

        self.assertEqual(result, 3)
        write.assert_called_once_with()

    def test_missing_concrete_tenant_fails_closed(self):
        with self.assertRaisesRegex(ValidationError, "TENANT_UNAVAILABLE"):
            execute_guarded_legacy_payslip_write(
                tenant_ids={None},
                operation="CREATE",
                object_refs=["new"],
                write=Mock(),
            )
