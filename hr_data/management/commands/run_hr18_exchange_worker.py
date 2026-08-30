"""Run a bounded batch of durable HR18 exchange jobs."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from hr_data.models import ExchangeJob
from hr_data.services.exchange_service import ExchangeError, ExchangeJobService


class Command(BaseCommand):
    help = "Transmit a bounded batch of queued HR18 exchange jobs"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
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
        self.stdout.write(
            self.style.SUCCESS(
                "HR18 exchange batch "
                f"candidates={len(candidates)} transmitted={transmitted} "
                f"retry={retried} dead_letter={dead} unavailable={unavailable}"
            )
        )
