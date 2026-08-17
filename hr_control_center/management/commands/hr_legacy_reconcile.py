"""Run tenant or all-tenant legacy cutover reconciliation as a production gate."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from hr_control_center.services.legacy_reconciliation_aggregator import (
    DOMAIN_CHOICES,
    GlobalLegacyReconciliationAggregator,
    LegacyReconciliationAggregator,
)


class Command(BaseCommand):
    help = "Run read-only HR15/HR16 reconciliation and HR18 legacy asset inventory"

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--tenant", type=int)
        scope.add_argument(
            "--all-tenants",
            action="store_true",
            help="Run tenant-isolated reconciliation for every Company",
        )
        parser.add_argument(
            "--domain",
            choices=DOMAIN_CHOICES,
            default="all",
        )
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument(
            "--fail-on-drift",
            action="store_true",
            help="Return non-zero unless the selected reconciliation is COMPLETE",
        )

    def handle(self, *args, **options):
        tenant_id = options.get("tenant")
        if tenant_id is not None and int(tenant_id) <= 0:
            raise CommandError("--tenant 必须是正整数")

        limit = int(options["limit"])
        if not 1 <= limit <= 500:
            raise CommandError("--limit 必须在 1..500")

        try:
            if options.get("all_tenants"):
                payload = GlobalLegacyReconciliationAggregator(limit=limit).run(
                    domain=options["domain"]
                )
            else:
                payload = LegacyReconciliationAggregator(
                    int(tenant_id),
                    limit=limit,
                ).run(domain=options["domain"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True))

        if options["fail_on_drift"] and payload["status"] != "COMPLETE":
            if options.get("all_tenants"):
                detail = ",".join(str(value) for value in payload["partialTenantIds"])
                if payload["status"] == "EMPTY":
                    detail = "NO_TENANTS"
            else:
                detail = ",".join(payload["partialPairs"])
            raise CommandError(
                f"legacy cutover reconciliation is {payload['status']}: {detail}"
            )
