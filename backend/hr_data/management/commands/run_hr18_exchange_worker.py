"""Run a bounded batch of durable HR18 exchange jobs."""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from base.worker_health import write_worker_heartbeat
from hr_data.models import ExchangeJob
from hr_data.services.exchange_service import ExchangeError, ExchangeJobService


class Command(BaseCommand):
    help = "Transmit a bounded batch of queued HR18 exchange jobs"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=float, default=5.0)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        interval = options["interval"]
        if not 1 <= interval <= 300:
            raise CommandError("--interval must be between 1 and 300 seconds")
        watch = options["watch"]
        while True:
            write_worker_heartbeat("hr18-exchange")
            candidates, summary = self._run_batch(limit)
            write_worker_heartbeat("hr18-exchange")
            if candidates or not watch:
                self.stdout.write(self.style.SUCCESS(summary))
            if not watch:
                return
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("HR18 exchange worker stopped")
                return

    def _run_batch(self, limit):
        now = timezone.now()
        candidates = list(
            ExchangeJob.objects.filter(
                Q(status=ExchangeJob.Status.QUEUED)
                | Q(
                    status=ExchangeJob.Status.RETRY_WAIT,
                    next_attempt_at__lte=now,
                )
                | Q(
                    status=ExchangeJob.Status.LEASED,
                    lease_expires_at__lte=now,
                )
            )
            .order_by("created_at")
            .values_list("tenant_id", "id")[:limit]
        )
        transmitted = retried = dead = unavailable = 0
        for tenant_id, job_id in candidates:
            write_worker_heartbeat("hr18-exchange")
            try:
                outcome = ExchangeJobService(tenant_id).dispatch(job_id)
            except ExchangeError as exc:
                # Another worker may have claimed the row after this bounded
                # candidate snapshot. That is normal; the lease guard decides.
                if exc.code == "EXCHANGE_PROVIDER_UNAVAILABLE":
                    unavailable += 1
                continue
            transmitted += int(outcome.transmitted)
            retried += int(outcome.retry_scheduled)
            dead += int(outcome.dead_lettered)
        return len(candidates), (
            "HR18 exchange batch "
            f"candidates={len(candidates)} transmitted={transmitted} "
            f"retry={retried} dead_letter={dead} unavailable={unavailable}"
        )
