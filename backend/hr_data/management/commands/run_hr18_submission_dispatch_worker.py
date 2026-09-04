"""Run a bounded batch of durable HR18 formal-submission dispatch jobs."""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from base.worker_health import write_worker_heartbeat
from hr_data.models import SubmissionDispatchJob
from hr_data.services.submission_dispatch_service import (
    SubmissionDispatchError,
    SubmissionDispatchService,
)


class Command(BaseCommand):
    help = "Dispatch a bounded batch of queued HR18 formal submissions"

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
            write_worker_heartbeat("hr18-submission")
            candidates, summary = self._run_batch(limit)
            write_worker_heartbeat("hr18-submission")
            if candidates or not watch:
                self.stdout.write(self.style.SUCCESS(summary))
            if not watch:
                return
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("HR18 submission dispatch worker stopped")
                return

    def _run_batch(self, limit):
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
            write_worker_heartbeat("hr18-submission")
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
        return len(candidates), (
            "HR18 submission dispatch "
            f"candidates={len(candidates)} submitted={submitted} "
            f"retry={retried} dead={dead} unavailable={unavailable} "
            f"contended={contended}"
        )
