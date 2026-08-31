"""
hr_staff/management/commands/hr03_migrate.py —— HR03 Legacy 迁移命令（S11）。

用法：
    python manage.py hr03_migrate --tenant <school_id> --wave 0,1,2,3,4,5

Wave 0 盘点；Wave 1 Person/StaffMaster；Wave 2 Relationship/Assignment；
Wave 3 Background/Materials；Wave 4 Reconciliation 样本矩阵；Wave 5 Authority cutover。
"""

from django.core.management.base import BaseCommand, CommandError

from hr_staff.legacy.migration import MigrationService
from hr_staff.legacy.reconciliation import ReconciliationService


class Command(BaseCommand):
    help = "HR03 Legacy → Authority 迁移（Wave 0-5）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="学校 tenant id")
        parser.add_argument("--wave", type=str, choices=["0", "1", "2", "3", "4", "5"], required=True)

    def handle(self, *args, **options):
        tenant_id = options["tenant"]
        wave = options["wave"]
        if not tenant_id:
            raise CommandError("--tenant 必填")

        if wave in ("0", "1", "2"):
            service = MigrationService(tenant_id)
            report = service.run_wave(wave)
            self.stdout.write(self.style.SUCCESS(report.summary()))
            for issue in report.issues:
                self.stdout.write(self.style.WARNING(f"  - {issue}"))
        elif wave == "3":
            # Wave 3: Background/Materials staging（文档材料迁移）
            self.stdout.write(self.style.WARNING("Wave 3 需人工审核背景事实与材料分类；请在盘点后独立执行"))
        elif wave == "4":
            # Wave 4: Reconciliation 样本矩阵
            result = ReconciliationService(tenant_id).reconcile_all()
            self.stdout.write(self.style.SUCCESS(
                f"对账完成：总计 {result['total']}，不一致 {result['mismatchCount']}"
            ))
            for m in result.get("mismatched", []):
                self.stdout.write(self.style.WARNING(f"  staff={m['staffId']} emp={m['legacyEmployeeId']} {m['issues']}"))
        elif wave == "5":
            # Wave 5: Authority cutover
            from hr_staff.services.authority_mode_service import AuthorityModeService

            AuthorityModeService().record_cutover(
                tenant_id=tenant_id,
                mode="HR03_AUTHORITY",
                reason="Wave 5 migration cutover",
                cutover_by="hr03_migrate command",
            )
            self.stdout.write(self.style.SUCCESS(f"Authority cutover recorded for tenant {tenant_id}"))

