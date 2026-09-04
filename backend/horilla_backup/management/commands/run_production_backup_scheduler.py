from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from base.worker_health import write_worker_heartbeat


def create_backup():
    close_old_connections()
    try:
        call_command("create_production_backup")
    finally:
        close_old_connections()


class Command(BaseCommand):
    help = "Run the single production backup scheduler process."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_job(
            write_worker_heartbeat,
            "interval",
            args=("backup-scheduler",),
            seconds=30,
            id="runtime.backup_scheduler_heartbeat",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.add_job(
            create_backup,
            "interval",
            hours=settings.PRODUCTION_BACKUP_INTERVAL_HOURS,
            id="encrypted-production-backup",
            next_run_time=datetime.now(timezone.utc),
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self.stdout.write(
            f"Starting production backup scheduler every {settings.PRODUCTION_BACKUP_INTERVAL_HOURS} hours"
        )
        write_worker_heartbeat("backup-scheduler")
        scheduler.start()
