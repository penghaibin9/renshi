"""Run tenant-scoped legacy cutover reconciliation/inventory as a production gate."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from hr_control_center.services.legacy_reconciliation_aggregator import (
    DOMAIN_CHOICES,
    LegacyReconciliationAggregator,
)


class Command(BaseCommand):
    help = "Run read-only HR15/HR16 reconciliation and HR18 legacy asset inventory"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument(
            "--domain",
            choices=DOMAIN_CHOICES,
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

        try:
            payload = LegacyReconciliationAggregator(
                tenant_id,
                limit=limit,
            ).run(domain=options["domain"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True))

        if options["fail_on_drift"] and payload["status"] != "COMPLETE":
            raise CommandError(
                "legacy cutover reconciliation is PARTIAL: "
                + ",".join(payload["partialPairs"])
            )
