"""Tenant-safe read-only reconciliation for legacy Horilla offboarding.

The legacy ``offboarding.OffboardingEmployee`` graph is a migration/read
source only. It must never become HR16 Authority merely because an old stage
looks complete. This service performs explicit-tenant dual-read correlation
without mutating either side or conflating legacy notice dates with formal
employment-end facts.
"""

from __future__ import annotations

from collections import defaultdict

from hr_exit.models import ExitFact


_LEGACY_TERMINAL_STAGE_TYPES = frozenset({"archived"})
_LEGACY_TERMINAL_PROCESS_STATUSES = frozenset({"completed"})


class LegacyExitReconciliationService:
    """Correlate one tenant's legacy offboarding rows with HR16 ExitFact.

    Background reconciliation deliberately bypasses the legacy thread-local
    manager via ``entire()`` and immediately reapplies an explicit tenant
    predicate. Legacy terminal/archived state and notice-period dates are only
    migration evidence: they never prove that EmploymentRelationship ended.
    """

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = int(tenant_id)

    def _legacy_rows(self, limit: int) -> tuple[int, list[dict]]:
        from offboarding.models import OffboardingEmployee

        qs = (
            OffboardingEmployee.objects.entire()
            .filter(employee_id__employee_work_info__company_id=self.tenant_id)
            .order_by("-notice_period_ends", "-id")
        )
        total = qs.count()
        rows = list(
            qs.values(
                "id",
                "employee_id_id",
                "notice_period_starts",
                "notice_period_ends",
                "stage_id_id",
                "stage_id__type",
                "stage_id__title",
                "stage_id__offboarding_id__status",
            )[:limit]
        )
        return total, rows

    def _staff_map(self, legacy_employee_ids: set[int]) -> dict[int, dict]:
        if not legacy_employee_ids:
            return {}
        from hr_staff.models import HrStaffMaster

        rows = HrStaffMaster.objects.filter(
            tenant_id=self.tenant_id,
            legacy_employee_id__in=legacy_employee_ids,
        ).values("id", "person_id_id", "legacy_employee_id")
        return {
            int(row["legacy_employee_id"]): {
                "staff_id": row["id"],
                "person_id": row["person_id_id"],
            }
            for row in rows
            if row["legacy_employee_id"] is not None
        }

    def _facts_by_person(self, person_ids: set[object]) -> dict[object, list[dict]]:
        if not person_ids:
            return {}
        grouped: dict[object, list[dict]] = defaultdict(list)
        rows = ExitFact.objects.filter(
            tenant_id=self.tenant_id,
            person_id__in=person_ids,
        ).values(
            "id",
            "person_id",
            "employment_relationship_id",
            "exit_type",
            "employment_end_date",
            "last_working_date",
            "status",
            "supersedes_fact_id",
        )
        for row in rows:
            grouped[row["person_id"]].append(row)
        return dict(grouped)

    @staticmethod
    def _legacy_terminal(row: dict) -> bool:
        stage_type = str(row.get("stage_id__type") or "").lower()
        process_status = str(
            row.get("stage_id__offboarding_id__status") or ""
        ).lower()
        return (
            stage_type in _LEGACY_TERMINAL_STAGE_TYPES
            or process_status in _LEGACY_TERMINAL_PROCESS_STATUSES
        )

    @staticmethod
    def _authority_terminal(rows: list[dict]) -> tuple[str, dict | None]:
        if not rows:
            return "AUTHORITY_FACT_MISSING", None

        terminal = [
            row
            for row in rows
            if row["status"]
            in {
                ExitFact.Status.EFFECTIVE,
                ExitFact.Status.REVISED,
                ExitFact.Status.REVOKED,
            }
        ]
        if not terminal:
            return "AUTHORITY_NOT_EFFECTIVE", None

        effective = [
            row
            for row in terminal
            if row["status"] == ExitFact.Status.EFFECTIVE
        ]
        if len(effective) != 1 or len(terminal) != 1:
            return "AUTHORITY_COMPLEX", None
        return "READY", effective[0]

    def snapshot(self, *, limit: int = 200) -> dict:
        limit = max(1, min(int(limit), 500))
        total, legacy_rows = self._legacy_rows(limit)
        truncated = total > len(legacy_rows)

        employee_ids = {int(row["employee_id_id"]) for row in legacy_rows}
        staff_map = self._staff_map(employee_ids)
        person_ids = {mapped["person_id"] for mapped in staff_map.values()}
        facts_by_person = self._facts_by_person(person_ids)

        counts = defaultdict(int)
        items = []
        for row in legacy_rows:
            stage_type = str(row.get("stage_id__type") or "").lower()
            process_status = str(
                row.get("stage_id__offboarding_id__status") or ""
            ).lower()
            legacy_terminal = self._legacy_terminal(row)
            item = {
                "legacyOffboardingEmployeeId": row["id"],
                "legacyEmployeeId": row["employee_id_id"],
                "legacyStageType": stage_type,
                "legacyStageTitle": row.get("stage_id__title") or "",
                "legacyProcessStatus": process_status,
                "legacyTerminalCandidate": legacy_terminal,
                "legacyAuthority": False,
                "legacyDateSemantics": "NOTICE_PERIOD_END",
                "noticePeriodStarts": row.get("notice_period_starts"),
                "noticePeriodEnds": row.get("notice_period_ends"),
                "staffId": None,
                "personId": None,
                "authorityExitFactId": None,
                "authorityDateSemantics": "EMPLOYMENT_END",
                "authorityEmploymentEndDate": None,
                "reconciliation": "LEGACY_NON_FINAL",
            }

            if not legacy_terminal:
                counts["legacyNonFinal"] += 1
                items.append(item)
                continue

            mapped = staff_map.get(int(row["employee_id_id"]))
            if mapped is None:
                item["reconciliation"] = "UNMAPPED_STAFF"
                counts["unmappedStaff"] += 1
                items.append(item)
                continue

            item["staffId"] = str(mapped["staff_id"])
            item["personId"] = str(mapped["person_id"])
            state, authority = self._authority_terminal(
                facts_by_person.get(mapped["person_id"], [])
            )
            if state != "READY":
                item["reconciliation"] = state
                count_key = {
                    "AUTHORITY_FACT_MISSING": "authorityFactMissing",
                    "AUTHORITY_NOT_EFFECTIVE": "authorityNotEffective",
                    "AUTHORITY_COMPLEX": "authorityComplex",
                }[state]
                counts[count_key] += 1
                items.append(item)
                continue

            item["authorityExitFactId"] = str(authority["id"])
            item["authorityEmploymentEndDate"] = authority["employment_end_date"]
            if row.get("notice_period_ends") is None:
                item["reconciliation"] = "LEGACY_NOTICE_END_MISSING"
                counts["legacyNoticeEndMissing"] += 1
                items.append(item)
                continue

            # HR16's frozen contract explicitly forbids treating Notice Period
            # End, planned resignation date, last working date, or contract end
            # as Employment End. Even equal calendar dates require mapping
            # evidence/human verification before legacy data can be certified.
            item["reconciliation"] = "LINKED_REVIEW_REQUIRED"
            counts["linkedReviewRequired"] += 1
            items.append(item)

        unresolved = sum(
            counts[key]
            for key in (
                "unmappedStaff",
                "authorityFactMissing",
                "authorityNotEffective",
                "authorityComplex",
                "legacyNoticeEndMissing",
                "linkedReviewRequired",
            )
        )
        status = "PARTIAL" if truncated or unresolved else "COMPLETE"
        return {
            "status": status,
            "authority": "HR16",
            "legacySource": "offboarding.OffboardingEmployee",
            "legacyAuthority": False,
            "mappingPolicy": "NOTICE_PERIOD_END_IS_NOT_EMPLOYMENT_END",
            "totalLegacyRows": total,
            "returnedRows": len(items),
            "truncated": truncated,
            "counts": dict(counts),
            "items": items,
        }
