"""Run legacy housekeeping jobs in one explicit process.

The original project started APScheduler from several package imports.  Under
Gunicorn that creates one copy per worker and can execute the same write many
times.  This command is the single runtime owner for those schedules.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from base.worker_health import write_worker_heartbeat

logger = logging.getLogger(__name__)


def _run_job(job):
    close_old_connections()
    try:
        job()
    except Exception:
        logger.exception("scheduled job failed: %s.%s", job.__module__, job.__name__)
        raise
    finally:
        close_old_connections()


def _add(scheduler, job, trigger, *, job_id, **trigger_args):
    scheduler.add_job(
        _run_job,
        trigger,
        args=(job,),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        **trigger_args,
    )


def build_scheduler():
    from base.canonical_hr_jobs import (
        anonymize_expired_recruitment_candidates,
        dispatch_external_academic_provisioning,
        dispatch_external_access_provisioning,
        expire_external_engagements,
        run_external_import_jobs,
        run_canonical_retirement_prechecks,
        scan_canonical_contract_expiry,
    )
    from asset.scheduler import (
        mark_expired_assets,
        notify_expiring_assets,
        notify_expiring_documents,
    )
    from attendance.scheduler import auto_punch_out, create_work_record
    from base.scheduler import (
        recurring_holiday,
        rotate_shift,
        rotate_work_type,
        switch_shift,
        switch_work_type,
        sync_roster_shifts,
        undo_shift,
        undo_work_type,
    )
    from leave.scheduler import leave_reset
    from pms.scheduler import cyclic_feedback_creation
    from recruitment.scheduler import candidate_convert, recruitment_close
    from biometric.scheduler import sync_biometric_jobs

    scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_job(
        write_worker_heartbeat,
        "interval",
        args=("legacy-scheduler",),
        seconds=30,
        id="runtime.legacy_scheduler_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    every_four_hours = (
        (rotate_shift, "base.rotate_shift"),
        (rotate_work_type, "base.rotate_work_type"),
        (undo_shift, "base.undo_shift"),
        (switch_shift, "base.switch_shift"),
        (undo_work_type, "base.undo_work_type"),
        (switch_work_type, "base.switch_work_type"),
        (recurring_holiday, "base.recurring_holiday"),
        (sync_roster_shifts, "base.sync_roster_shifts"),
        (notify_expiring_documents, "asset.notify_expiring_documents"),
        (leave_reset, "leave.reset"),
    )
    for job, job_id in every_four_hours:
        _add(scheduler, job, "interval", job_id=job_id, hours=4)

    _add(
        scheduler,
        notify_expiring_assets,
        "interval",
        job_id="asset.notify_expiring_assets",
        days=1,
    )
    _add(
        scheduler,
        mark_expired_assets,
        "interval",
        job_id="asset.mark_expired_assets",
        days=1,
    )
    _add(
        scheduler,
        candidate_convert,
        "interval",
        job_id="recruitment.convert_candidates",
        minutes=5,
    )
    _add(
        scheduler,
        recruitment_close,
        "interval",
        job_id="recruitment.close",
        hours=1,
    )
    _add(
        scheduler,
        cyclic_feedback_creation,
        "cron",
        job_id="pms.cyclic_feedback",
        hour=8,
        misfire_grace_time=24 * 60 * 60,
    )
    _add(
        scheduler,
        create_work_record,
        "interval",
        job_id="attendance.create_work_record_interval",
        minutes=30,
        misfire_grace_time=3 * 60 * 60,
    )
    _add(
        scheduler,
        create_work_record,
        "cron",
        job_id="attendance.create_work_record_daily",
        hour=0,
        minute=30,
        misfire_grace_time=9 * 60 * 60,
    )
    _add(
        scheduler,
        auto_punch_out,
        "interval",
        job_id="attendance.auto_punch_out",
        minutes=5,
        misfire_grace_time=10 * 60,
    )
    _add(
        scheduler,
        dispatch_external_access_provisioning,
        "interval",
        job_id="hr08.iam_provisioning_dispatch",
        minutes=1,
        misfire_grace_time=5 * 60,
    )
    _add(
        scheduler,
        dispatch_external_academic_provisioning,
        "interval",
        job_id="hr08.academic_provisioning_dispatch",
        minutes=1,
        misfire_grace_time=5 * 60,
    )
    _add(
        scheduler,
        run_external_import_jobs,
        "interval",
        job_id="hr08.import_job_runner",
        minutes=2,
        misfire_grace_time=10 * 60,
    )
    _add(
        scheduler,
        expire_external_engagements,
        "cron",
        job_id="hr08.expire_engagements",
        hour=0,
        minute=15,
        misfire_grace_time=12 * 60 * 60,
    )
    _add(
        scheduler,
        anonymize_expired_recruitment_candidates,
        "cron",
        job_id="hr04.candidate_retention",
        hour=1,
        minute=30,
        misfire_grace_time=12 * 60 * 60,
    )
    _add(
        scheduler,
        run_canonical_retirement_prechecks,
        "cron",
        job_id="hr16.canonical_retirement_prechecks",
        hour=2,
        minute=0,
        misfire_grace_time=12 * 60 * 60,
    )
    _add(
        scheduler,
        scan_canonical_contract_expiry,
        "cron",
        job_id="hr07.canonical_contract_expiry",
        hour=2,
        minute=30,
        misfire_grace_time=12 * 60 * 60,
    )
    scheduler.add_job(
        sync_biometric_jobs,
        "interval",
        args=(scheduler,),
        seconds=30,
        id="biometric.reconcile_schedules",
        next_run_time=datetime.now(timezone.utc),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


class Command(BaseCommand):
    help = "Run the single legacy housekeeping scheduler process."

    def handle(self, *args, **options):
        scheduler = build_scheduler()
        write_worker_heartbeat("legacy-scheduler")
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting dedicated legacy scheduler with {len(scheduler.get_jobs())} jobs"
            )
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write("Legacy scheduler stopped")
