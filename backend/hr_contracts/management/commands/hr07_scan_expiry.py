"""Run the canonical HR07 expiry worker for one explicit tenant/date."""

from __future__ import annotations

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from horilla.horilla_middlewares import tenant_context
from hr_contracts.services.alert_escalation import (
    CanonicalContractExpiryService,
    ContractExpiryError,
)


class Command(BaseCommand):
    help = "Scan canonical HR07 contract expiry facts for one tenant."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--as-of", required=True)
        parser.add_argument("--actor-user-id", type=int)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            as_of = date.fromisoformat(options["as_of"])
        except (TypeError, ValueError) as error:
            raise CommandError("--as-of must use YYYY-MM-DD") from error
        try:
            with tenant_context(options["tenant_id"]):
                result = CanonicalContractExpiryService(
                    options["tenant_id"],
                    actor_user_id=options.get("actor_user_id"),
                ).scan(
                    as_of=as_of,
                    dry_run=options["dry_run"],
                    limit=options["limit"],
                )
        except ContractExpiryError as error:
            raise CommandError(f"{error.code}: {error}") from error
        self.stdout.write(
            json.dumps(result, ensure_ascii=True, sort_keys=True, default=str)
        )
