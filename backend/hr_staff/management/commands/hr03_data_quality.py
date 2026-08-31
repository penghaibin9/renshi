"""
hr_staff/management/commands/hr03_data_quality.py —— HR03 数据质量扫描命令（P2 接线）。

用法：python manage.py hr03_data_quality --tenant <id> [--as-of 2026-08-09]
"""

from django.core.management.base import BaseCommand, CommandError

from hr_staff.services.data_quality_service import DataQualityService


class Command(BaseCommand):
    help = "HR03 数据质量异常扫描"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--as-of", type=str, default=None)

    def handle(self, *args, **options):
        tenant_id = options["tenant"]
        if not tenant_id:
            raise CommandError("--tenant 必填")
        as_of = None
        if options["as_of"]:
            from django.utils.dateparse import parse_date

            as_of = parse_date(options["as_of"])
            if as_of is None:
                raise CommandError(f"无效日期: {options['as_of']}")
        result = DataQualityService(tenant_id, as_of=as_of).scan()
        self.stdout.write(self.style.SUCCESS(f"数据质量异常总数: {result['total']}"))
        for issue in result["issues"]:
            self.stdout.write(
                f"  - [{issue['severity']}] {issue['rule']} staff={issue['staffNo']} {issue['message']}"
            )
