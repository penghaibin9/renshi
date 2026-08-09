"""
hr_qualification/management/commands/hr09_legacy_migrate.py —— Legacy Migration（总册 §171/S10）。

将旧 Employee.qualification 字符串迁移为 HrPersonCredential。

流程：
1. 扫描 Employee.qualification 非空记录
2. 尝试匹配已知 catalog code
3. 无法匹配 → exception queue
4. 已匹配 → 创建 HrPersonCredential（MIGRATED_UNVERIFIED 状态）
"""

from django.core.management.base import BaseCommand
from django.db import transaction


_KEYWORD_TO_CATALOG = {
    "高校教师资格": "TQ-HEDU",
    "高等学校教师资格": "TQ-HEDU",
    "高校教师": "TQ-HEDU",
    "中等职业学校教师资格": "TQ-SVTE",
    "中职教师资格": "TQ-SVTE",
    "国家职业资格一级": "VQ-L1",
    "国家职业资格二级": "VQ-L2",
    "高级技师": "VQ-L1",
    "技师": "VQ-L2",
    "职业技能等级一级": "SL-L1",
    "非教师系列": "NT-SEN",
}


class Command(BaseCommand):
    help = "将 Legacy Employee.qualification 迁移到 HrPersonCredential（S10）。"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        try:
            from employee.models import Employee, EmployeeWorkInformation
        except ImportError:
            self.stdout.write(self.style.ERROR("employee module not available"))
            return

        try:
            from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
        except ImportError:
            self.stdout.write(self.style.ERROR("hr_qualification models not available"))
            return

        qs = Employee.objects.filter(
            employee_work_info__company_id=tenant_id,
            is_active=True,
        ).exclude(qualification__isnull=True).exclude(qualification="")

        if limit:
            qs = qs[:limit]

        matched = 0
        unmatched = 0
        skipped = 0
        created = 0

        for emp in qs:
            text = (emp.qualification or "").strip()
            if not text:
                skipped += 1
                continue

            catalog_code = None
            for keyword, code in _KEYWORD_TO_CATALOG.items():
                if keyword in text:
                    catalog_code = code
                    break

            if not catalog_code:
                unmatched += 1
                self.stdout.write(f"  UNMATCHED: Employee#{emp.id} '{text[:60]}'")
                continue

            try:
                catalog_item = HrCredentialCatalogItem.objects.get(code=catalog_code)
            except HrCredentialCatalogItem.DoesNotExist:
                unmatched += 1
                continue

            # 检查是否已有同 catalog 的 credential
            if HrPersonCredential.objects.filter(
                tenant_id=tenant_id,
                credential_name_snapshot__icontains=catalog_item.name,
                staff_master_id__isnull=False,
            ).exists():
                skipped += 1
                continue

            if not dry_run:
                with transaction.atomic():
                    HrPersonCredential.objects.create(
                        tenant_id=tenant_id,
                        person_id_id=None,  # 需要 HR03 mapping
                        credential_name_snapshot=catalog_item.name,
                        catalog_item_id=catalog_item,
                        issuer_name=catalog_item.issuer_type,
                        source="MIGRATED",
                        self_reported=False,
                        current_verification_status="MIGRATED_UNVERIFIED",
                    )

            matched += 1
            created += 1 if not dry_run else 0

        self.stdout.write(self.style.SUCCESS(
            f"Legacy migration {'[DRY RUN] ' if dry_run else ''}complete:\n"
            f"  matched={matched}, unmatched={unmatched}, skipped={skipped}, created={created}"
        ))
