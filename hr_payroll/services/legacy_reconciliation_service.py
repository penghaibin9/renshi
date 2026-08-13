"""Tenant-safe read-only reconciliation for legacy Horilla payroll.

The legacy ``payroll.Payslip`` table is a migration source, never HR15 authority.
This service performs double-read comparison without mutating either side.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from hr_payroll.models import PayrollPeriod, PayrollResultFact


_MONEY_QUANT = Decimal("0.01")
_LEGACY_TERMINAL = frozenset({"confirmed", "paid"})


def _money(value) -> Decimal:
    """Normalize legacy FloatField money without carrying binary float noise."""
    if value in (None, ""):
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"LEGACY_PAYROLL_INVALID_MONEY: {value!r}") from exc


class LegacyPayrollReconciliationService:
    """Compare legacy payslips with HR15 authority facts for one tenant.

    No method in this class writes legacy rows or HR15 authority rows.  Legacy
    ``confirmed``/``paid`` states are only reconciliation candidates and are
    never promoted to HR15 FINALIZED by this reader.
    """

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = int(tenant_id)

    def _legacy_rows(self, limit: int) -> tuple[int, list[dict]]:
        from payroll.models.models import Payslip

        qs = Payslip.objects.filter(
            employee_id__employee_work_info__company_id=self.tenant_id
        ).order_by("-end_date", "-id")
        total = qs.count()
        rows = list(
            qs.values(
                "id",
                "employee_id_id",
                "start_date",
                "end_date",
                "gross_pay",
                "deduction",
                "net_pay",
                "status",
            )[:limit]
        )
        return total, rows

    def _staff_map(self, legacy_employee_ids: set[int]) -> dict[int, object]:
        if not legacy_employee_ids:
            return {}
        from hr_staff.models import HrStaffMaster

        return dict(
            HrStaffMaster.objects.filter(
                tenant_id=self.tenant_id,
                legacy_employee_id__in=legacy_employee_ids,
            ).values_list("legacy_employee_id", "id")
        )

    def _period_map(self, ranges: set[tuple]) -> dict[tuple, object]:
        if not ranges:
            return {}
        starts = {start for start, _ in ranges}
        ends = {end for _, end in ranges}
        rows = PayrollPeriod.objects.filter(
            tenant_id=self.tenant_id,
            start_date__in=starts,
            end_date__in=ends,
        ).values("id", "start_date", "end_date")
        return {
            (row["start_date"], row["end_date"]): row["id"]
            for row in rows
            if (row["start_date"], row["end_date"]) in ranges
        }

    def _result_map(self, period_ids: set[object]) -> dict[tuple, list[dict]]:
        if not period_ids:
            return {}
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        rows = PayrollResultFact.objects.filter(
            tenant_id=self.tenant_id,
            payroll_period_id__in=period_ids,
        ).values(
            "id",
            "payroll_period_id",
            "staff_id",
            "gross_amount",
            "deduction_amount",
            "net_amount",
            "status",
            "supersedes_result_id",
        )
        for row in rows:
            grouped[(row["payroll_period_id"], row["staff_id"])].append(row)
        return dict(grouped)

    @staticmethod
    def _authority_terminal(rows: list[dict]) -> tuple[str, dict | None]:
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
        finalized = [
            row for row in terminal if row["status"] == PayrollResultFact.Status.FINALIZED
        ]
        # Once adjustments/reversals exist, a simple one-row comparison can no
        # longer represent the authoritative effective amount safely.
        if len(finalized) != 1 or len(terminal) != 1:
            return "AUTHORITY_COMPLEX", None
        return "READY", finalized[0]

    def snapshot(self, *, limit: int = 200) -> dict:
        limit = max(1, min(int(limit), 500))
        total, legacy_rows = self._legacy_rows(limit)
        truncated = total > len(legacy_rows)

        employee_ids = {int(row["employee_id_id"]) for row in legacy_rows}
        staff_map = self._staff_map(employee_ids)
        ranges = {(row["start_date"], row["end_date"]) for row in legacy_rows}
        period_map = self._period_map(ranges)
        result_map = self._result_map(set(period_map.values()))

        counts = defaultdict(int)
        items = []
        for row in legacy_rows:
            legacy_status = str(row.get("status") or "").lower()
            item = {
                "legacyPayslipId": row["id"],
                "legacyEmployeeId": row["employee_id_id"],
                "legacyStatus": legacy_status,
                "legacyAuthority": False,
                "startDate": row["start_date"],
                "endDate": row["end_date"],
                "staffId": None,
                "payrollPeriodId": None,
                "authorityResultId": None,
                "reconciliation": "LEGACY_NON_FINAL",
            }

            if legacy_status not in _LEGACY_TERMINAL:
                counts["legacyNonFinal"] += 1
                items.append(item)
                continue

            staff_id = staff_map.get(int(row["employee_id_id"]))
            if staff_id is None:
                item["reconciliation"] = "UNMAPPED_STAFF"
                counts["unmappedStaff"] += 1
                items.append(item)
                continue
            item["staffId"] = str(staff_id)

            period_id = period_map.get((row["start_date"], row["end_date"]))
            if period_id is None:
                item["reconciliation"] = "AUTHORITY_PERIOD_MISSING"
                counts["authorityPeriodMissing"] += 1
                items.append(item)
                continue
            item["payrollPeriodId"] = str(period_id)

            state, authority = self._authority_terminal(
                result_map.get((period_id, staff_id), [])
            )
            if state != "READY":
                item["reconciliation"] = state
                counts[
                    "authorityComplex"
                    if state == "AUTHORITY_COMPLEX"
                    else "authorityResultMissing"
                ] += 1
                items.append(item)
                continue

            item["authorityResultId"] = str(authority["id"])
            legacy_amounts = (
                _money(row.get("gross_pay")),
                _money(row.get("deduction")),
                _money(row.get("net_pay")),
            )
            authority_amounts = (
                _money(authority.get("gross_amount")),
                _money(authority.get("deduction_amount")),
                _money(authority.get("net_amount")),
            )
            if legacy_amounts == authority_amounts:
                item["reconciliation"] = "MATCHED"
                counts["matched"] += 1
            else:
                item["reconciliation"] = "AMOUNT_MISMATCH"
                item["legacyAmounts"] = {
                    "gross": str(legacy_amounts[0]),
                    "deduction": str(legacy_amounts[1]),
                    "net": str(legacy_amounts[2]),
                }
                item["authorityAmounts"] = {
                    "gross": str(authority_amounts[0]),
                    "deduction": str(authority_amounts[1]),
                    "net": str(authority_amounts[2]),
                }
                counts["amountMismatch"] += 1
            items.append(item)

        unresolved = sum(
            counts[key]
            for key in (
                "unmappedStaff",
                "authorityPeriodMissing",
                "authorityResultMissing",
                "authorityComplex",
                "amountMismatch",
            )
        )
        status = "PARTIAL" if truncated or unresolved else "COMPLETE"
        return {
            "status": status,
            "authority": "HR15",
            "legacySource": "payroll.Payslip",
            "legacyAuthority": False,
            "totalLegacyRows": total,
            "returnedRows": len(items),
            "truncated": truncated,
            "counts": dict(counts),
            "items": items,
        }
