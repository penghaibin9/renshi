"""Employee scheduled jobs.

This module defines jobs only. It must never start APScheduler at import time.
Run the dedicated worker with ``python manage.py run_employee_scheduler``.
"""

from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from base.worker_health import write_worker_heartbeat
from horilla.horilla_middlewares import tenant_context


def _for_each_company(job):
    """Execute one legacy job once per concrete school/tenant."""
    from base.models import Company

    for company_id in Company.objects.values_list("id", flat=True).iterator():
        with tenant_context(company_id):
            job()


def update_experience():
    from employee.models import EmployeeWorkInformation

    queryset = EmployeeWorkInformation.objects.filter(employee_id__is_active=True)
    for instance in queryset.iterator():
        instance.experience_calculator()


def block_unblock_disciplinary():
    from base.models import EmployeeShiftSchedule
    from employee.models import DisciplinaryAction
    from horilla_auth.models import HorillaUser

    today = date.today()
    now = datetime.now().time()
    dis_actions = DisciplinaryAction.objects.select_related("action").prefetch_related(
        "employee_id"
    )

    for dis in dis_actions:
        if not dis.action.block_option:
            continue

        employees = dis.employee_id.exclude(employee_user_id__isnull=True)
        user_ids = list(employees.values_list("employee_user_id", flat=True))
        if not user_ids:
            continue

        if dis.action.action_type == "suspension":
            active = None
            if dis.days:
                start_date = dis.start_date
                end_date = start_date + timedelta(days=dis.days)
                if today >= end_date:
                    active = True
                elif today >= start_date:
                    active = False

            if dis.hours:
                if today != dis.start_date:
                    continue
                hour_time = datetime.strptime(dis.hours + ":00", "%H:%M:%S").time()
                for emp in employees:
                    if not emp.employee_work_info:
                        continue
                    shift = emp.employee_work_info.shift_id
                    shift_today = EmployeeShiftSchedule.objects.filter(
                        shift_id=shift, day__day=datetime.today().strftime("%A").lower()
                    ).first()
                    if not shift_today:
                        continue
                    st_time = shift_today.start_time
                    suspension_end_time = (
                        datetime.combine(today, st_time)
                        + timedelta(
                            hours=hour_time.hour,
                            minutes=hour_time.minute,
                            seconds=hour_time.second,
                        )
                    ).time()
                    if now >= suspension_end_time:
                        active = True
                    elif now >= st_time:
                        active = False
                    user = emp.employee_user_id
                    if user and active is not None:
                        user.is_active = active
                        user.save(update_fields=["is_active"])

            if dis.days and active is not None:
                HorillaUser.objects.filter(id__in=user_ids).update(is_active=active)

        elif dis.action.action_type == "dismissal" and today >= dis.start_date:
            HorillaUser.objects.filter(id__in=user_ids).update(is_active=False)


def update_experience_all_tenants():
    _for_each_company(update_experience)


def block_unblock_disciplinary_all_tenants():
    _for_each_company(block_unblock_disciplinary)


def build_scheduler(*, blocking=False):
    scheduler_cls = BlockingScheduler if blocking else BackgroundScheduler
    scheduler = scheduler_cls(timezone="UTC")
    scheduler.add_job(
        write_worker_heartbeat,
        "interval",
        args=("employee-scheduler",),
        seconds=30,
        id="runtime.employee_scheduler_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        update_experience_all_tenants,
        "interval",
        hours=4,
        id="employee.update_experience",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        block_unblock_disciplinary_all_tenants,
        "interval",
        seconds=60,
        id="employee.block_unblock_disciplinary",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
