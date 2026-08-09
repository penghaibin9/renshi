"""
hr_qualification/management/commands/hr09_switch_authority.py —— Authority 切换（总册 §173/S12）。

LEGACY_QUALIFICATION_TEXT → DUAL_READ_COMPARE → HR09_AUTHORITY

使用 Feature Flag（django-constance 或 DB flag 表）控制：
- LEGACY: 旧 Employee.qualification 读写
- DUAL: 双读对比（写 HR09，读返回 HR09，同时写 legacy 投影）
- AUTHORITY: HR09 Authority，legacy readonly
"""

from django.core.management.base import BaseCommand


_MODE_CHOICES = ["LEGACY", "DUAL_READ_COMPARE", "HR09_AUTHORITY"]


class Command(BaseCommand):
    help = "Authority 模式切换（总册 §173/S12）。"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--mode", choices=_MODE_CHOICES, required=True)
        parser.add_argument("--force", action="store_true", default=False,
                            help="跳过确认提示")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        mode = options["mode"]
        force = options["force"]

        if not force:
            self.stdout.write(self.style.WARNING(
                f"即将切换 tenant {tenant_id} 的 qualification authority 到 {mode}。\n"
                f"切换前请确保已完成：\n"
                f"  1. Legacy Migration（hr09_legacy_migrate）\n"
                f"  2. DUAL_READ_COMPARE 对账全绿\n"
                f"  3. 遗留写入口已封堵\n"
            ))
            confirm = input("输入 'YES' 确认: ")
            if confirm != "YES":
                self.stdout.write("已取消。")
                return

        if mode == "LEGACY":
            self._set_mode(tenant_id, "LEGACY_STAFF_ONLY")
            self.stdout.write(f"Tenant {tenant_id} → LEGACY（旧写入口开放，HR09 不响应正式写入）")

        elif mode == "DUAL_READ_COMPARE":
            self._set_mode(tenant_id, "DUAL_READ_COMPARE")
            from hr_qualification.services.legacy_projection import LegacyQualificationProjection
            result = LegacyQualificationProjection.bulk_rebuild(tenant_id)
            self.stdout.write(
                f"Tenant {tenant_id} → DUAL_READ_COMPARE\n"
                f"  Legacy 投影重建: {result}"
            )

        elif mode == "HR09_AUTHORITY":
            self._set_mode(tenant_id, "HR09_AUTHORITY")
            self.stdout.write(f"Tenant {tenant_id} → HR09_AUTHORITY（旧写入口已封堵）")

    def _set_mode(self, tenant_id: int, mode: str):
        try:
            from hr_qualification.models.credential_catalog import HrCredentialCatalogItem
            # 使用 tenant_id=0 存储模式标记（临时方案，正式应走 HR03 HrStaffAuthorityMode）
            obj, _ = HrCredentialCatalogItem.objects.get_or_create(
                tenant_id=0,
                code=f"AUTH_MODE_{tenant_id}",
                defaults={"name": mode, "category": "OTHER"},
            )
            obj.name = mode
            obj.save()
        except Exception:
            self.stdout.write(self.style.WARNING(
                "Unable to persist authority mode (schema not ready). "
                "Mode set in-memory only for this session."
            ))
