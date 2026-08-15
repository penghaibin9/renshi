"""Run the HR01-HR18 runtime Authority gate."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from hr_control_center.services.authority_gate_service import AuthorityGateService


class Command(BaseCommand):
    help = "Validate HR01-HR18 Authority, canonical API and legacy cutover contracts"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int)
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument(
            "--require-reconciliation",
            action="store_true",
            help="Require an explicit tenant and COMPLETE HR15/16/18 reconciliation",
        )
        parser.add_argument(
            "--fail-on-partial",
            action="store_true",
            help="Return non-zero when the Authority Gate is not COMPLETE",
        )

    def handle(self, *args, **options):
        tenant_id = options.get("tenant")
        if tenant_id is not None and int(tenant_id) <= 0:
            raise CommandError("--tenant 必须是正整数")
        limit = int(options["limit"])
        if not 1 <= limit <= 500:
            raise CommandError("--limit 必须在 1..500")

        payload = AuthorityGateService(
            tenant_id=tenant_id,
            limit=limit,
        ).run(require_reconciliation=options["require_reconciliation"])
        self.stdout.write(json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True))

        if options["fail_on_partial"] and payload["status"] != "COMPLETE":
            raise CommandError("HR01-HR18 Authority Gate is PARTIAL")
