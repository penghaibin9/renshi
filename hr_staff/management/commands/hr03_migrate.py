"""
hr_staff/management/commands/hr03_migrate.py —— HR03 Legacy 迁移命令（S11）。

用法：
    python manage.py hr03_migrate --tenant <school_id> --wave 0
    python manage.py hr03_migrate --tenant <school_id> --wave 1
    python manage.py hr03_migrate --tenant <school_id> --wave 2

Wave 0 只盘点；Wave 1 Person/StaffMaster；Wave 2 Relationship/Assignment。
"""

from django.core.management.base import BaseCommand, CommandError

from hr_staff.legacy.migration import MigrationService


class Command(BaseCommand):
    help = "HR03 Legacy → Authority 迁移（Wave 0/1/2）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="学校 tenant id")
        parser.add_argument("--wave", type=str, choices=["0", "1", "2"], required=True)

    def handle(self, *args, **options):
        tenant_id = options["tenant"]
        wave = options["wave"]
        if not tenant_id:
            raise CommandError("--tenant 必填")
        service = MigrationService(tenant_id)
        report = service.run_wave(wave)
        self.stdout.write(self.style.SUCCESS(report.summary()))
        for issue in report.issues:
            self.stdout.write(self.style.WARNING(f"  - {issue}"))
