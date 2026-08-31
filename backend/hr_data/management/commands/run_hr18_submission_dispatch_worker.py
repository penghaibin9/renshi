"""Run a bounded batch of durable HR18 formal-submission dispatch jobs."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from hr_data.models import SubmissionDispatchJob
from hr_data.services.submission_dispatch_service import (
    SubmissionDispatchError,
    SubmissionDispatchService,
)


class Command(BaseCommand):
    help = "Dispatch a bounded batch of queued HR18 formal submissions"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        now = timezone.now()
        candidates = list(
            SubmissionDispatchJob.objects.filter(
                Q(status=SubmissionDispatchJob.Status.QUEUED)
                | Q(
                    status=SubmissionDispatchJob.Status.RETRY_WAIT,
                    next_attempt_at__lte=now,
                )
                | Q(
                    status=SubmissionDispatchJob.Status.LEASED,
                    lease_expires_at__lte=now,
                )
            )
            .order_by("created_at")
            .values_list("tenant_id", "id")[:limit]
        )
        submitted = retried = dead = unavailable = contended = 0
        for tenant_id, job_id in candidates:
            try:
                outcome = SubmissionDispatchService(tenant_id).dispatch(job_id)
            except SubmissionDispatchError as exc:
                if exc.code == "SUBMISSION_DISPATCH_UNAVAILABLE":
                    unavailable += 1
                else:
                    contended += 1
                continue
            submitted += int(outcome.submitted)
            retried += int(outcome.retry_scheduled)
            dead += int(outcome.dead)
        self.stdout.write(
            self.style.SUCCESS(
                "HR18 submission dispatch "
                f"candidates={len(candidates)} submitted={submitted} "
                f"retry={retried} dead={dead} unavailable={unavailable} "
                f"contended={contended}"
            )
        )
