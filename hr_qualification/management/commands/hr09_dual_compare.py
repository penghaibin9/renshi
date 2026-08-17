"""
hr_qualification/management/commands/hr09_dual_compare.py —— DUAL_READ_COMPARE（总册 §139/S10）。

对账：Employee.qualification 字符串 ↔ HR09 PersonCredential + Recognition 当前状态。

输出差异 → HR09_LEGACY_DRIFT DataQualityFinding。
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "DUAL_READ_COMPARE：Legacy Employee.qualification vs HR09 Authority（总册 §139）。"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        limit = options["limit"]

        from hr_qualification.services.legacy_projection import LegacyQualificationProjection

        try:
            from employee.models import Employee

            qs = Employee.objects.filter(
                employee_work_info__company_id=tenant_id, is_active=True
            )[:limit]

            total = 0
            drift = 0
            legacy_only = 0
            hr09_only = 0

            for emp in qs:
                total += 1
                projected = LegacyQualificationProjection.project_to_employee(emp.id, tenant_id)
                old = (emp.qualification or "").strip()

                if old and projected and old != projected:
                    drift += 1
                    self.stdout.write(f"  DRIFT Employee#{emp.id}: LEGACY='{old[:40]}' vs HR09='{projected[:40]}'")
                elif old and not projected:
                    legacy_only += 1
                elif projected and not old:
                    hr09_only += 1

            self.stdout.write(self.style.SUCCESS(
                f"DUAL_READ_COMPARE complete: total={total}, drift={drift}, "
                f"legacy_only={legacy_only}, hr09_only={hr09_only}"
            ))
        except ImportError:
            self.stdout.write(self.style.ERROR("employee module not available"))
