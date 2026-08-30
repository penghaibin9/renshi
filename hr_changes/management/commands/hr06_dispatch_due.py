"""
hr_changes/management/commands/hr06_dispatch_due.py

到期异动生效调度（S8）。
用法：python manage.py hr06_dispatch_due [--tenant=1]
可挂入 cron / APScheduler。
"""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from horilla.horilla_middlewares import tenant_context
from hr_changes.jobs.apply_due_cases import run_due_applications


class Command(BaseCommand):
    help = "Dispatch due personnel change applications (HR06)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="tenant_id")
        parser.add_argument("--as-of", required=True, help="业务日期 YYYY-MM-DD")
        parser.add_argument("--actor-user-id", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            as_of = date.fromisoformat(options["as_of"])
        except (TypeError, ValueError) as exc:
            raise CommandError("--as-of must use YYYY-MM-DD") from exc
        with tenant_context(options["tenant"]):
            result = run_due_applications(
                tenant_id=options["tenant"],
                as_of=as_of,
                actor_user_id=options.get("actor_user_id"),
                dry_run=options["dry_run"],
            )
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
