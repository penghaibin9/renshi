"""
hr05_switch_authority —— HR05 Authority 切换管理命令（00 §56 / 05 §44）。

用法：
  python manage.py hr05_switch_authority --tenant 1 --mode HR05_AUTHORITY \
      --reason "对账通过" --report reconcile-001

规则：
- tenant 级切换；禁止全局一锅端；
- 进入 HR05_AUTHORITY 前建议先跑 hr05_reconcile_legacy 对账；
- 记录 operator/old_mode/new_mode/reason/reconcile_report_id。
"""

from django.core.management.base import BaseCommand

from hr_onboarding.models import HrOnboardingAuthorityMode
from hr_onboarding.policies.authority import switch_authority_mode


class Command(BaseCommand):
    help = "切换 HR05 权威模式（LEGACY_ONBOARDING_ONLY / DUAL_READ_COMPARE / HR05_AUTHORITY）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="学校 tenant_id")
        parser.add_argument("--mode", required=True, choices=HrOnboardingAuthorityMode.Mode.values)
        parser.add_argument("--reason", default="", help="切换原因")
        parser.add_argument("--report", default="", help="对账报告 ID")
        parser.add_argument("--operator", type=int, default=None, help="操作人 user id")

    def handle(self, *args, **options):
        record = switch_authority_mode(
            tenant_id=options["tenant"],
            target_mode=options["mode"],
            operator_user_id=options["operator"],
            reason=options["reason"],
            reconcile_report_id=options["report"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"tenant={record.tenant_id} mode={record.mode} "
                f"(old={record.old_mode or '-'} new={record.new_mode or '-'})"
            )
        )
