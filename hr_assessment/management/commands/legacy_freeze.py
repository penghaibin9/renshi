"""HR12 Legacy PMS Write Freeze 管理命令 (S12)。

使用 Django cache 或文件标记控制旧 PMS 写操作拦截。
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand

HR12_FREEZE_KEY = "hr12_legacy_pms_write_frozen"
HR12_FREEZE_LOG_KEY = "hr12_freeze_log"


class Command(BaseCommand):
    help = "冻结/解冻旧 PMS 写操作"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["freeze", "unfreeze", "status"])
        parser.add_argument("--reason", default="")
        parser.add_argument("--operator", default="SYSTEM")

    def handle(self, **options):
        action = options["action"]

        if action == "freeze":
            self._do_freeze(options["reason"], options["operator"])
        elif action == "unfreeze":
            self._do_unfreeze(options["reason"], options["operator"])
        elif action == "status":
            self._show_status()

    def _do_freeze(self, reason: str, operator: str):
        cache.set(HR12_FREEZE_KEY, True, timeout=None)
        logs = cache.get(HR12_FREEZE_LOG_KEY, [])
        logs.insert(0, {"action": "freeze", "operator": operator, "reason": reason})
        cache.set(HR12_FREEZE_LOG_KEY, logs[:50], timeout=None)
        self.stdout.write(self.style.SUCCESS(
            f"✅ Legacy PMS write endpoints FROZEN — operator={operator} reason={reason}"
        ))

    def _do_unfreeze(self, reason: str, operator: str):
        cache.delete(HR12_FREEZE_KEY)
        logs = cache.get(HR12_FREEZE_LOG_KEY, [])
        logs.insert(0, {"action": "unfreeze", "operator": operator, "reason": reason})
        cache.set(HR12_FREEZE_LOG_KEY, logs[:50], timeout=None)
        self.stdout.write(self.style.WARNING(
            f"⚠️ Legacy PMS write endpoints UNFROZEN (rollback) — operator={operator}"
        ))

    def _show_status(self):
        frozen = cache.get(HR12_FREEZE_KEY, False)
        logs = cache.get(HR12_FREEZE_LOG_KEY, [])
        if frozen:
            self.stdout.write("Status: FROZEN — 旧 PMS 写操作已冻结")
        else:
            self.stdout.write("Status: ACTIVE — 旧 PMS 写操作仍可用")
        if logs:
            self.stdout.write(f"最近操作: {logs[0]}")


def is_pms_write_frozen() -> bool:
    """在 PMS 视图中调用此函数判断是否应阻断写操作。"""
    return bool(cache.get(HR12_FREEZE_KEY, False))
