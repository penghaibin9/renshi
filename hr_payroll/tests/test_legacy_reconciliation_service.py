import inspect
import uuid
from decimal import Decimal

from django.test import SimpleTestCase

from hr_payroll.models import PayrollResultFact
from hr_payroll.services.legacy_reconciliation_service import (
    LegacyPayrollReconciliationService,
    _money,
)


class StubLegacyPayrollReconciliationService(LegacyPayrollReconciliationService):
    def __init__(self, *, legacy_rows, staff_map, period_map, result_map, total=None):
        super().__init__(tenant_id=7)
        self.legacy_rows = legacy_rows
        self.staff_map = staff_map
        self.period_map = period_map
        self.result_map = result_map
        self.total = len(legacy_rows) if total is None else total

    def _legacy_rows(self, limit):
        return self.total, self.legacy_rows[:limit]

    def _staff_map(self, legacy_employee_ids):
        return self.staff_map

    def _period_map(self, ranges):
        return self.period_map

    def _result_map(self, period_ids):
        return self.result_map


class Hr15LegacyReconciliationTests(SimpleTestCase):
    def _legacy(self, *, status="paid", gross=1000.1, deduction=100.1, net=900.0):
        return {
            "id": 81,
            "employee_id_id": 18,
            "start_date": "2026-07-01",
            "end_date": "2026-08-01",
            "gross_pay": gross,
            "deduction": deduction,
            "net_pay": net,
            "status": status,
        }

    def test_float_money_is_normalized_to_decimal_cents(self):
        self.assertEqual(_money(1000.1), Decimal("1000.10"))
        self.assertEqual(_money(None), Decimal("0.00"))

    def test_matching_legacy_terminal_row_remains_non_authoritative(self):
        staff_id = uuid.uuid4()
        period_id = uuid.uuid4()
        result_id = uuid.uuid4()
        svc = StubLegacyPayrollReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={18: staff_id},
            period_map={("2026-07-01", "2026-08-01"): period_id},
            result_map={
                (period_id, staff_id): [
                    {
                        "id": result_id,
                        "status": PayrollResultFact.Status.FINALIZED,
                        "gross_amount": Decimal("1000.10"),
                        "deduction_amount": Decimal("100.10"),
                        "net_amount": Decimal("900.00"),
                        "supersedes_result_id": None,
                    }
                ]
            },
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "COMPLETE")
        self.assertFalse(snapshot["legacyAuthority"])
        self.assertEqual(snapshot["items"][0]["reconciliation"], "MATCHED")
        self.assertFalse(snapshot["items"][0]["legacyAuthority"])

    def test_unmapped_legacy_staff_is_partial_not_silently_dropped(self):
        svc = StubLegacyPayrollReconciliationService(
            legacy_rows=[self._legacy(status="confirmed")],
            staff_map={},
            period_map={},
            result_map={},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["counts"]["unmappedStaff"], 1)
        self.assertEqual(snapshot["items"][0]["reconciliation"], "UNMAPPED_STAFF")

    def test_adjustment_chain_is_not_flattened_into_false_match(self):
        staff_id = uuid.uuid4()
        period_id = uuid.uuid4()
        base_id = uuid.uuid4()
        svc = StubLegacyPayrollReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={18: staff_id},
            period_map={("2026-07-01", "2026-08-01"): period_id},
            result_map={
                (period_id, staff_id): [
                    {
                        "id": base_id,
                        "status": PayrollResultFact.Status.FINALIZED,
                        "gross_amount": Decimal("1000.10"),
                        "deduction_amount": Decimal("100.10"),
                        "net_amount": Decimal("900.00"),
                        "supersedes_result_id": None,
                    },
                    {
                        "id": uuid.uuid4(),
                        "status": PayrollResultFact.Status.ADJUSTED,
                        "gross_amount": Decimal("10.00"),
                        "deduction_amount": Decimal("0.00"),
                        "net_amount": Decimal("10.00"),
                        "supersedes_result_id": base_id,
                    },
                ]
            },
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["items"][0]["reconciliation"], "AUTHORITY_COMPLEX")

    def test_non_final_legacy_row_is_inventory_only(self):
        svc = StubLegacyPayrollReconciliationService(
            legacy_rows=[self._legacy(status="review_ongoing")],
            staff_map={},
            period_map={},
            result_map={},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "COMPLETE")
        self.assertEqual(snapshot["counts"]["legacyNonFinal"], 1)
        self.assertEqual(snapshot["items"][0]["reconciliation"], "LEGACY_NON_FINAL")

    def test_legacy_reader_and_staff_mapping_are_tenant_scoped(self):
        legacy_source = inspect.getsource(LegacyPayrollReconciliationService._legacy_rows)
        staff_source = inspect.getsource(LegacyPayrollReconciliationService._staff_map)
        self.assertIn(
            "employee_id__employee_work_info__company_id=self.tenant_id",
            legacy_source,
        )
        self.assertIn("tenant_id=self.tenant_id", staff_source)
