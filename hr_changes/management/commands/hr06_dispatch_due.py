"""
hr_changes/management/commands/hr06_dispatch_due.py

到期异动生效调度（S8）。
用法：python manage.py hr06_dispatch_due [--tenant=1]
可挂入 cron / APScheduler。
"""

from django.core.management.base import BaseCommand

from hr_changes.jobs.apply_due_cases import run_due_applications


class Command(BaseCommand):
    help = "Dispatch due personnel change applications (HR06)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, default=None, help="tenant_id（缺省=全部）")

    def handle(self, *args, **options):
        result = run_due_applications(tenant_id=options.get("tenant"))
        self.stdout.write(
            self.style.SUCCESS(
                f"due={result['total']} applied={result['applied']} failed={result['failed']}"
            )
        )
