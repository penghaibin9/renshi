"""
hr_structure/management/commands/seed_hr02_defaults.py

HR02 默认字典种子（幂等）：
- 岗位等级方案（管理/专技/工勤 三类默认模板，总册 12.3）
- 不写死为全局唯一，tenant 级可配置

用法：python manage.py seed_hr02_defaults --tenant=1
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from hr_structure.models import HrPostGrade, HrPostGradeScheme


class Command(BaseCommand):
    help = "Seed HR02 default post grade schemes (idempotent, per tenant)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="tenant_id")

    def handle(self, *args, **options):
        tenant_id = options["tenant"]
        created = 0

        # 专业技术岗位 13 级（总册 12.2/12.3：专技一级~十三级）
        scheme, was_created = HrPostGradeScheme.objects.get_or_create(
            tenant_id=tenant_id,
            code="PROF_TECH_GRADE",
            defaults={
                "name": "专业技术岗位等级",
                "category": "PROFESSIONAL_TECHNICAL",
                "validity_from": timezone.localdate(),
            },
        )
        if was_created:
            grades = [
                ("一级", 1, 1), ("二级", 2, 2), ("三级", 3, 3), ("四级", 4, 4),
                ("五级", 5, 5), ("六级", 6, 6), ("七级", 7, 7), ("八级", 8, 8),
                ("九级", 9, 9), ("十级", 10, 10), ("十一级", 11, 11),
                ("十二级", 12, 12), ("十三级", 13, 13),
            ]
            for name, rank, level in grades:
                HrPostGrade.objects.create(
                    scheme_id=scheme,
                    code=f"PT{level:02d}",
                    name=f"专技{name}",
                    rank_order=rank,
                    level_number=level,
                    is_entry_level=(level == 13),
                    is_top_level=(level == 1),
                )
            created += 1

        # 管理岗位 10 级（一级~十级）
        scheme2, was2 = HrPostGradeScheme.objects.get_or_create(
            tenant_id=tenant_id,
            code="MGMT_GRADE",
            defaults={
                "name": "管理岗位等级",
                "category": "MANAGEMENT",
                "validity_from": timezone.localdate(),
            },
        )
        if was2:
            for level in range(1, 11):
                HrPostGrade.objects.create(
                    scheme_id=scheme2,
                    code=f"MG{level:02d}",
                    name=f"管理{level}级",
                    rank_order=level,
                    level_number=level,
                    is_entry_level=(level == 10),
                    is_top_level=(level == 1),
                )
            created += 1

        # 工勤技能岗位 5 级（一级~五级）
        scheme3, was3 = HrPostGradeScheme.objects.get_or_create(
            tenant_id=tenant_id,
            code="SKILL_GRADE",
            defaults={
                "name": "工勤技能岗位等级",
                "category": "SKILLED_WORKER",
                "validity_from": timezone.localdate(),
            },
        )
        if was3:
            for level in range(1, 6):
                HrPostGrade.objects.create(
                    scheme_id=scheme3,
                    code=f"SK{level:02d}",
                    name=f"工勤{level}级",
                    rank_order=level,
                    level_number=level,
                    is_entry_level=(level == 5),
                    is_top_level=(level == 1),
                )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} grade schemes for tenant {tenant_id}: "
                f"{scheme.code}({scheme.grades.count()}), "
                f"{scheme2.code}({scheme2.grades.count()}), "
                f"{scheme3.code}({scheme3.grades.count()})"
            )
        )
