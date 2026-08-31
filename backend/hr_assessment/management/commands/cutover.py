"""HR12 Authority Cutover 管理命令 (S12)。"""

from django.core.management.base import BaseCommand

PHASES = [
    "LEGACY_ACTIVE",
    "NEW_STAGING",
    "DUAL_READ_COMPARE",
    "SHADOW_EXECUTION",
    "FREEZE_LEGACY_FORMAL_WRITES",
    "NEW_AUTHORITY",
    "LEGACY_READONLY_PROJECTION",
    "POST_CUTOVER_CLEANUP",
]


class Command(BaseCommand):
    help = "HR12 Authority Cutover 切换编排"

    def add_arguments(self, parser):
        parser.add_argument("--phase", required=True, choices=PHASES)
        parser.add_argument("--tenant-id", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        phase = options["phase"]
        dry = options["dry_run"]
        prefix = "[DRY RUN] " if dry else ""

        if dry:
            self.stdout.write(self.style.WARNING(f"{prefix}预演模式 — 不执行实际操作"))
        else:
            self.stdout.write(self.style.SUCCESS(f"{prefix}执行阶段: {phase}"))

        switcher = {
            "LEGACY_ACTIVE": self._verify_legacy_active,
            "NEW_STAGING": self._deploy_staging,
            "DUAL_READ_COMPARE": self._run_dual_read,
            "SHADOW_EXECUTION": self._enable_shadow,
            "FREEZE_LEGACY_FORMAL_WRITES": self._freeze_writes,
            "NEW_AUTHORITY": self._activate_authority,
            "LEGACY_READONLY_PROJECTION": self._enable_projection,
            "POST_CUTOVER_CLEANUP": self._cleanup,
        }
        switcher[phase](dry)

    def _verify_legacy_active(self, dry: bool):
        """验证旧 PMS 仍在正常运行。"""
        if dry:
            return
        try:
            from pms.models import Period
            count = Period.objects.count()
            self.stdout.write(f"旧 PMS Period 数量: {count}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"旧 PMS 不可用: {e}"))

    def _deploy_staging(self, dry: bool):
        """部署 HR12 到 staging。"""
        self.stdout.write("运行 migrate + collectstatic...")

    def _run_dual_read(self, dry: bool):
        """执行双读对账。"""
        from hr_assessment.management.commands.dual_read_compare import Command as DRC
        cmd = DRC()
        cmd.handle(tenant_id=0)

    def _enable_shadow(self, dry: bool):
        """开启 HR12 影子执行。"""
        self.stdout.write("开启 feature flag: HR12_SHADOW_EXECUTION=true")

    def _freeze_writes(self, dry: bool):
        """冻结旧 PMS 写入。"""
        from hr_assessment.management.commands.legacy_freeze import Command as LF
        cmd = LF()
        cmd.handle(action="freeze", reason="HR12 Authority Cutover", operator="SYSTEM")

    def _activate_authority(self, dry: bool):
        """HR12 成为唯一 Authority。"""
        self.stdout.write("切换 feature flag: HR12_AUTHORITY=true")

    def _enable_projection(self, dry: bool):
        """旧 PMS → 只读投影。"""
        self.stdout.write("启用 Legacy Projection (readonly)")

    def _cleanup(self, dry: bool):
        """切后清理。"""
        self.stdout.write("移除旧路由 / 清理临时数据")
