"""Database-driven biometric schedules owned by the dedicated scheduler process."""

import logging

from django.db import close_old_connections

from biometric.models import BiometricDevices

logger = logging.getLogger(__name__)

JOB_PREFIX = "biometric.device."


def schedule_seconds(value):
    """Convert the stored HH:MM[:SS] duration to a positive interval."""
    try:
        parts = [int(part) for part in str(value).split(":")]
    except (TypeError, ValueError):
        return 0
    if len(parts) == 2:
        hours, minutes = parts
        seconds = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        return 0
    if min(hours, minutes, seconds) < 0 or minutes >= 60 or seconds >= 60:
        return 0
    return hours * 3600 + minutes * 60 + seconds


def run_biometric_device_schedule(device_id):
    """Run one due device sync after rechecking its current database state."""
    close_old_connections()
    try:
        device = BiometricDevices.objects.filter(
            id=device_id, is_active=True, is_scheduler=True
        ).first()
        if not device:
            return

        # Import lazily so importing URL/view modules never starts a scheduler.
        from biometric import views

        runners = {
            "zk": views.zk_biometric_attendance_scheduler,
            "anviz": views.anviz_biometric_attendance_scheduler,
            "cosec": views.cosec_biometric_attendance_scheduler,
            "dahua": views.dahua_biometric_attendance_scheduler,
            "etimeoffice": views.etimeoffice_biometric_attendance_scheduler,
        }
        runner = runners.get(device.machine_type)
        if runner:
            runner(device.id)
    except Exception:
        logger.exception("Biometric schedule failed for device %s", device_id)
        raise
    finally:
        close_old_connections()


def sync_biometric_jobs(scheduler):
    """Reconcile APScheduler jobs with active database device schedules."""
    close_old_connections()
    try:
        desired = {}
        for device in BiometricDevices.objects.filter(
            is_active=True, is_scheduler=True
        ).only("id", "scheduler_duration"):
            interval = schedule_seconds(device.scheduler_duration)
            if interval > 0:
                desired[f"{JOB_PREFIX}{device.id}"] = (device.id, interval)

        existing = {
            job.id: job
            for job in scheduler.get_jobs()
            if job.id.startswith(JOB_PREFIX)
        }
        for job_id in set(existing) - set(desired):
            scheduler.remove_job(job_id)

        for job_id, (device_id, interval) in desired.items():
            job = existing.get(job_id)
            current_interval = (
                job.trigger.interval.total_seconds()
                if job and hasattr(job.trigger, "interval")
                else None
            )
            if current_interval == interval:
                continue
            scheduler.add_job(
                run_biometric_device_schedule,
                "interval",
                args=(device_id,),
                seconds=interval,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
    except Exception:
        logger.exception("Unable to reconcile biometric scheduler jobs")
    finally:
        close_old_connections()

