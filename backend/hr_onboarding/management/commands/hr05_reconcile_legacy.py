"""
hr05_reconcile_legacy —— HR05 DUAL_READ_COMPARE 对账命令（05 §45）。

用法：
  python manage.py hr05_reconcile_legacy --tenant 1

输出：legacy vs authority 计数 + discrepancy 列表（前 200 条）。
禁止"新系统空就读旧系统"、禁止自动 fallback。
"""

from django.core.management.base import BaseCommand

from hr_onboarding.jobs.reconcile import reconcile_legacy


class Command(BaseCommand):
    help = "HR05 legacy↔authority 对账（DUAL_READ_COMPARE）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)

    def handle(self, *args, **options):
        report = reconcile_legacy(tenant_id=options["tenant"])
        self.stdout.write(
            self.style.SUCCESS(
                f"tenant={report['tenant_id']} legacy_started={report['legacy_started_count']} "
                f"authority_cases={report['authority_cases_count']} "
                f"discrepancy={report['discrepancy_count']}"
            )
        )
        for d in report["discrepancies"]:
            self.stdout.write(self.style.WARNING(f"  DISCREPANCY: {d}"))
