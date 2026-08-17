"""
hr_changes/management/commands/hr06_reconcile_legacy.py

双读对账（S10）：HR03 facts ↔ legacy WorkInformation 投影一致性。
用法：python manage.py hr06_reconcile_legacy [--tenant=1]
只发现/记录 HR06_PROJECTION_DRIFT，不静默修复权威数据。
"""

from django.core.management.base import BaseCommand

from hr_changes.jobs.reconcile_projection import run_reconcile


class Command(BaseCommand):
    help = "Reconcile HR03 facts vs legacy WorkInformation projection (HR06 S10)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, default=None, help="tenant_id（缺省=全部）")

    def handle(self, *args, **options):
        result = run_reconcile(tenant_id=options.get("tenant"), only_drift=False)
        self.stdout.write(
            self.style.SUCCESS(
                f"checked={result['checked']} drifted={result['drifted']}"
            )
        )
        for drift in result["staffDrifts"][:20]:
            self.stdout.write(
                self.style.WARNING(
                    f"  {drift['staffNo']} {drift['staffName']}: "
                    + "; ".join(d["field"] for d in drift["drifts"])
                )
            )
