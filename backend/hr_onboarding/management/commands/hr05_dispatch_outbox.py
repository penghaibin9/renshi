"""Continuously or once dispatch the production HR05 outbox."""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from base.worker_health import write_worker_heartbeat
from hr_onboarding.jobs.outbox_dispatcher import dispatch_pending
from hr_onboarding.jobs.production_outbox_handlers import build_production_registry


class Command(BaseCommand):
    help = "投递 HR05 outbox PENDING 事件（权威事实校验/幂等/重试/死信）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, default=None)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--worker-id", type=str, default=None)
        parser.add_argument("--lease-seconds", type=int, default=120)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=float, default=5.0)

    def handle(self, *args, **options):
        limit = int(options["limit"])
        interval = float(options["interval"])
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        if not 1 <= interval <= 300:
            raise CommandError("--interval must be between 1 and 300 seconds")
        registry = build_production_registry()
        while True:
            write_worker_heartbeat("hr05-outbox")
            result = dispatch_pending(
                tenant_id=options["tenant"],
                limit=limit,
                worker_id=options["worker_id"],
                lease_seconds=options["lease_seconds"],
                registry=registry,
            )
            write_worker_heartbeat("hr05-outbox")
            if result["total"] or not options["watch"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"dispatched={result['dispatched']} retrying={result['retrying']} "
                        f"failed={result['failed']} lost={result['lost']} total={result['total']}"
                    )
                )
            if not options["watch"]:
                return
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("HR05 outbox worker stopped")
                return
