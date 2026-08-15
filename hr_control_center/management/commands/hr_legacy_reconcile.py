"""Run tenant-scoped legacy cutover reconciliation/inventory as a production gate."""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder


_NON_DRIFT_COUNT_KEYS = frozenset(
    {"matched", "legacyNonFinal", "nonAuthorityPreferenceAsset"}
)


def _drift_count(snapshot: dict) -> int:
    counts = snapshot.get("counts") or {}
    return sum(
        int(value or 0)
        for key, value in counts.items()
        if key not in _NON_DRIFT_COUNT_KEYS
    )


class Command(BaseCommand):
    help = "Run read-only HR15/HR16 reconciliation and HR18 legacy asset inventory"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument(
            "--domain",
            choices=("all", "hr15", "hr16", "hr18"),
            default="all",
        )
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            help="Return non-zero when any selected cutover report is PARTIAL",
        )

    def handle(self, *args, **options):
        tenant_id = int(options["tenant"] or 0)
        if tenant_id <= 0:
            raise CommandError("--tenant 必须是正整数")

        limit = int(options["limit"])
        if not 1 <= limit <= 500:
            raise CommandError("--limit 必须在 1..500")

        domain = options["domain"]
        selected = []
        if domain in {"all", "hr15"}:
            selected.append("HR15")
        if domain in {"all", "hr16"}:
            selected.append("HR16")
        if domain in {"all", "hr18"}:
            selected.append("HR18_ASSET")

        started = time.monotonic()
        pairs: dict[str, dict] = {}
        durations: dict[str, float] = {}
        for pair in selected:
            pair_started = time.monotonic()
            if pair == "HR15":
                from hr_payroll.services.legacy_reconciliation_service import (
                    LegacyPayrollReconciliationService,
                )

                snapshot = LegacyPayrollReconciliationService(tenant_id).snapshot(
                    limit=limit
                )
            elif pair == "HR16":
                from hr_exit.services.legacy_reconciliation_service import (
                    LegacyExitReconciliationService,
                )

                snapshot = LegacyExitReconciliationService(tenant_id).snapshot(
                    limit=limit
                )
            else:
                from hr_data.services.legacy_report_asset_service import (
                    LegacyReportAssetInventoryService,
                )

                snapshot = LegacyReportAssetInventoryService(tenant_id).snapshot(
                    limit=limit
                )
            pairs[pair] = snapshot
            durations[pair] = round(time.monotonic() - pair_started, 6)

        drift_by_pair = {pair: _drift_count(data) for pair, data in pairs.items()}
        partial_pairs = [
            pair for pair, data in pairs.items() if data.get("status") != "COMPLETE"
        ]
        payload = {
            "schemaVersion": "hr.legacy-reconciliation-gate.2",
            "tenantId": tenant_id,
            "status": "PARTIAL" if partial_pairs else "COMPLETE",
            "selectedPairs": selected,
            "partialPairs": partial_pairs,
            "reconciliationDriftTotal": sum(drift_by_pair.values()),
            "reconciliationDriftByPair": drift_by_pair,
            "reconciliationExecutionDurationSeconds": round(
                time.monotonic() - started,
                6,
            ),
            "pairExecutionDurationSeconds": durations,
            "pairs": pairs,
        }
        self.stdout.write(json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True))

        if options["fail_on_drift"] and partial_pairs:
            raise CommandError(
                "legacy cutover reconciliation is PARTIAL: " + ",".join(partial_pairs)
            )
