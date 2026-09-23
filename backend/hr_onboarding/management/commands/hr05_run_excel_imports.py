"""Run confirmed HR05 Excel jobs outside request workers."""

from __future__ import annotations

import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from base.worker_health import write_worker_heartbeat
from hr_onboarding.models import HrOnboardingImportJob
from hr_onboarding.services.excel_service import COMMIT_STALE_SECONDS, commit_persisted_import


class Command(BaseCommand):
    help = "执行已确认的 HR05 Excel 导入（持久化、可恢复、跨 Web worker）"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=float, default=3.0)

    def handle(self, *args, **options):
        limit = int(options["limit"])
        interval = float(options["interval"])
        if not 1 <= limit <= 100:
            raise CommandError("--limit must be between 1 and 100")
        if not 1 <= interval <= 300:
            raise CommandError("--interval must be between 1 and 300 seconds")
        while True:
            write_worker_heartbeat("hr05-import")
            count = self._run_batch(limit)
            write_worker_heartbeat("hr05-import")
            if count or not options["watch"]:
                self.stdout.write(self.style.SUCCESS(f"HR05 Excel worker processed={count}"))
            if not options["watch"]:
                return
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("HR05 Excel import worker stopped")
                return

    def _run_batch(self, limit: int) -> int:
        stale_before = timezone.now() - timedelta(seconds=COMMIT_STALE_SECONDS)
        candidates = list(
            HrOnboardingImportJob.objects.filter(
                status=HrOnboardingImportJob.Status.COMMITTING,
            )
            .filter(Q(commit_started_at__isnull=True) | Q(commit_started_at__lt=stale_before))
            .order_by("updated_at", "created_at")
            .values_list("tenant_id", "id", "confirmed_by", "uploaded_by")[:limit]
        )
        processed = 0
        for tenant_id, job_id, confirmed_by, uploaded_by in candidates:
            write_worker_heartbeat("hr05-import")
            try:
                commit_persisted_import(
                    tenant_id=int(tenant_id),
                    job_id=job_id,
                    actor_user_id=(confirmed_by if confirmed_by is not None else uploaded_by),
                )
            except Exception as exc:  # noqa: BLE001 - job state preserves retry evidence
                self.stderr.write(f"HR05 Excel job {job_id} failed to claim/execute: {exc}")
                continue
            processed += 1
        return processed
